use axum::extract::ws::Message;
use dashmap::{DashMap, DashSet};
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::HashSet;
use std::sync::Arc;
use tokio::sync::mpsc;

#[derive(Clone, Debug, Serialize)]
pub(crate) struct ConnectionInfo {
    pub(crate) connection_id: String,
    pub(crate) user_id: String,
    pub(crate) subjects: Vec<String>,
    pub(crate) connected_at: i64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) traceparent: Option<String>,
}

struct ConnectionEntry {
    info: ConnectionInfo,
    sender: mpsc::Sender<Message>,
}

#[derive(Clone)]
pub(crate) struct ConnectionManager {
    connections: Arc<DashMap<String, ConnectionEntry>>,
    subjects: Arc<DashMap<String, DashSet<String>>>,
}

pub(crate) struct SendStats {
    pub(crate) sent: usize,
    pub(crate) dropped: usize,
}

pub(crate) struct SendOutcome {
    pub(crate) sent: bool,
    pub(crate) dropped: bool,
}

impl ConnectionManager {
    pub(crate) fn new() -> Self {
        Self {
            connections: Arc::new(DashMap::new()),
            subjects: Arc::new(DashMap::new()),
        }
    }

    pub(crate) async fn add(&self, info: ConnectionInfo, sender: mpsc::Sender<Message>) {
        let conn_id = info.connection_id.clone();
        for subject in &info.subjects {
            let entry = self
                .subjects
                .entry(subject.to_string())
                .or_insert_with(DashSet::new);
            entry.insert(conn_id.clone());
        }
        self.connections.insert(conn_id, ConnectionEntry { info, sender });
    }

    pub(crate) async fn remove(&self, connection_id: &str) -> Option<ConnectionInfo> {
        let entry = self.connections.remove(connection_id);
        if let Some((_key, entry)) = &entry {
            for subject in &entry.info.subjects {
                if let Some(set) = self.subjects.get(subject) {
                    set.remove(connection_id);
                    let empty = set.is_empty();
                    drop(set);
                    if empty {
                        self.subjects.remove(subject);
                    }
                }
            }
        }
        entry.map(|(_, entry)| entry.info)
    }

    pub(crate) async fn send_to_subjects(&self, subjects: &[String], payload: &Value) -> SendStats {
        let message = json!({"type": "event", "payload": payload});
        let text = match serde_json::to_string(&message) {
            Ok(text) => text,
            Err(_) => {
                return SendStats {
                    sent: 0,
                    dropped: 0,
                }
            }
        };
        self.send_text_to_subjects(subjects, &text).await
    }

    pub(crate) async fn send_text_to_subjects(
        &self,
        subjects: &[String],
        text: &str,
    ) -> SendStats {
        let mut targets = HashSet::new();
        for subject in subjects {
            if let Some(ids) = self.subjects.get(subject) {
                for id in ids.iter() {
                    targets.insert((*id).clone());
                }
            }
        }
        let mut senders = Vec::with_capacity(targets.len());
        for id in targets {
            if let Some(entry) = self.connections.get(&id) {
                senders.push(entry.sender.clone());
            }
        }
        let mut sent = 0;
        let mut dropped = 0;
        let message = text.to_string();
        for sender in senders {
            match sender.try_send(Message::Text(message.clone())) {
                Ok(_) => sent += 1,
                Err(tokio::sync::mpsc::error::TrySendError::Full(_)) => dropped += 1,
                Err(tokio::sync::mpsc::error::TrySendError::Closed(_)) => {}
            }
        }
        SendStats { sent, dropped }
    }

    pub(crate) async fn send_message(&self, connection_id: &str, message: Message) -> SendOutcome {
        let sender = self
            .connections
            .get(connection_id)
            .map(|entry| entry.sender.clone());
        match sender {
            Some(sender) => match sender.try_send(message) {
                Ok(_) => SendOutcome {
                    sent: true,
                    dropped: false,
                },
                Err(tokio::sync::mpsc::error::TrySendError::Full(_)) => SendOutcome {
                    sent: false,
                    dropped: true,
                },
                Err(tokio::sync::mpsc::error::TrySendError::Closed(_)) => SendOutcome {
                    sent: false,
                    dropped: false,
                },
            },
            None => SendOutcome {
                sent: false,
                dropped: false,
            },
        }
    }

    pub(crate) async fn list_connections(
        &self,
        subject: Option<String>,
        user_id: Option<String>,
    ) -> Vec<ConnectionInfo> {
        let mut results = Vec::new();
        for entry in self.connections.iter() {
            if let Some(ref s) = subject {
                if !entry.info.subjects.iter().any(|item| item == s) {
                    continue;
                }
            }
            if let Some(ref uid) = user_id {
                if entry.info.user_id != *uid {
                    continue;
                }
            }
            results.push(entry.info.clone());
        }
        results
    }
}
