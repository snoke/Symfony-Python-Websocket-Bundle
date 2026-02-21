<?php

namespace App\Controller;

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\Routing\Annotation\Route;
use Snoke\WsBundle\Service\WebsocketPublisher;
use Snoke\WsBundle\Contract\PresenceProviderInterface;

class ChatDemoController
{
    #[Route('/demo/chat', name: 'demo_chat', methods: ['GET'])]
    public function chatPage(): Response
    {
        $html = <<<'HTML'
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Mini Chat Demo</title>
    <style>
      :root {
        color-scheme: light;
      }
      body {
        font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
        margin: 0;
        background: linear-gradient(135deg, #f7f4ef 0%, #f0f7ff 100%);
        color: #1d1d1f;
      }
      .wrap {
        max-width: 980px;
        margin: 32px auto;
        padding: 24px;
        display: grid;
        gap: 16px;
        grid-template-columns: 2fr 1fr;
      }
      .card {
        background: #fff;
        border: 1px solid #e6e6e6;
        border-radius: 12px;
        box-shadow: 0 6px 24px rgba(0,0,0,0.06);
        padding: 16px;
      }
      .messages {
        height: 420px;
        overflow: auto;
        padding: 8px;
        border: 1px solid #ececec;
        border-radius: 8px;
        background: #fafafa;
      }
      .msg {
        margin: 8px 0;
        padding: 8px 12px;
        border-radius: 8px;
        background: #fff;
        border: 1px solid #eee;
      }
      .msg .meta {
        font-size: 12px;
        color: #6b6b6b;
      }
      .row {
        display: flex;
        gap: 8px;
      }
      input[type="text"] {
        flex: 1;
        padding: 10px 12px;
        border: 1px solid #dcdcdc;
        border-radius: 8px;
        font-size: 14px;
      }
      button {
        padding: 10px 14px;
        border: none;
        border-radius: 8px;
        background: #1f6feb;
        color: #fff;
        font-weight: 600;
        cursor: pointer;
      }
      button:disabled { opacity: 0.6; cursor: not-allowed; }
      .status {
        font-size: 12px;
        color: #555;
      }
      ul { list-style: none; padding: 0; margin: 0; }
      li { padding: 6px 0; border-bottom: 1px solid #f0f0f0; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <h2>Mini Chatroom</h2>
        <div class="status" id="status">connecting...</div>
        <div class="messages" id="messages"></div>
        <div class="row" style="margin-top: 12px;">
          <input id="message" type="text" placeholder="Type a message..." />
          <button id="send">Send</button>
        </div>
      </div>
      <div class="card">
        <h3>Online</h3>
        <ul id="online"></ul>
      </div>
    </div>
    <script>
      const statusEl = document.getElementById('status');
      const messagesEl = document.getElementById('messages');
      const onlineEl = document.getElementById('online');
      const sendBtn = document.getElementById('send');
      const msgInput = document.getElementById('message');

      const userId = localStorage.getItem('demo_user_id') || String(Math.floor(Math.random() * 10000));
      localStorage.setItem('demo_user_id', userId);

      function appendMessage(payload) {
        const div = document.createElement('div');
        div.className = 'msg';
        const meta = document.createElement('div');
        meta.className = 'meta';
        const when = payload.ts ? new Date(payload.ts * 1000).toLocaleTimeString() : '';
        meta.textContent = `${payload.user || 'anon'} ${when}`;
        const body = document.createElement('div');
        body.textContent = payload.text || '';
        div.appendChild(meta);
        div.appendChild(body);
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }

      async function refreshOnline() {
        try {
          const resp = await fetch('/api/online');
          const data = await resp.json();
          const connections = Array.isArray(data.connections) ? data.connections : [];
          const users = Array.from(new Set(connections.map(c => c.user_id).filter(Boolean)));
          onlineEl.innerHTML = '';
          if (users.length === 0) {
            const li = document.createElement('li');
            li.textContent = 'no users yet';
            onlineEl.appendChild(li);
            return;
          }
          users.forEach(u => {
            const li = document.createElement('li');
            li.textContent = `user:${u}`;
            onlineEl.appendChild(li);
          });
        } catch (e) {
          // ignore
        }
      }

      async function getToken() {
        const resp = await fetch(`/api/demo/token?user_id=${encodeURIComponent(userId)}`);
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.message || 'failed to fetch token');
        }
        const data = await resp.json();
        return data.token;
      }

      async function connect() {
        try {
          const token = await getToken();
          const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
          const wsUrl = `${wsProto}://${location.host}/ws?token=${encodeURIComponent(token)}`;
          const ws = new WebSocket(wsUrl);
          ws.onopen = () => {
            statusEl.textContent = `connected as user:${userId}`;
          };
          ws.onmessage = (ev) => {
            try {
              const msg = JSON.parse(ev.data);
              if (msg.type === 'event' && msg.payload) {
                appendMessage(msg.payload);
              }
            } catch (e) {
              // ignore
            }
          };
          ws.onclose = () => {
            statusEl.textContent = 'disconnected';
          };
          ws.onerror = () => {
            statusEl.textContent = 'error';
          };

          sendBtn.onclick = async () => {
            const text = msgInput.value.trim();
            if (!text) return;
            msgInput.value = '';
            await fetch('/api/demo/chat/send', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ user: `user:${userId}`, text })
            });
          };
        } catch (e) {
          statusEl.textContent = `failed: ${e.message}`;
          sendBtn.disabled = true;
        }
      }

      refreshOnline();
      setInterval(refreshOnline, 5000);
      connect();
    </script>
  </body>
</html>
HTML;

        return new Response($html);
    }

    #[Route('/api/demo/token', name: 'demo_token', methods: ['GET'])]
    public function demoToken(Request $request): JsonResponse
    {
        $userId = (string) $request->query->get('user_id', 'demo');
        if ($userId === '') {
            $userId = 'demo';
        }
        $privateKeyFile = $_ENV['DEMO_JWT_PRIVATE_KEY_FILE'] ?? '';
        $secret = $_ENV['DEMO_JWT_SECRET'] ?? '';
        $alg = $_ENV['DEMO_JWT_ALG'] ?? 'RS256';

        $header = ['typ' => 'JWT', 'alg' => $alg];
        $payload = [
            'user_id' => $userId,
            'iat' => time(),
            'exp' => time() + 3600,
        ];

        $signingInput = $this->base64UrlEncode(json_encode($header)).'.'.$this->base64UrlEncode(json_encode($payload));

        $signature = '';
        if (str_starts_with($alg, 'RS')) {
            if ($privateKeyFile === '' || !is_file($privateKeyFile)) {
                return new JsonResponse(['message' => 'missing DEMO_JWT_PRIVATE_KEY_FILE'], 500);
            }
            $key = file_get_contents($privateKeyFile);
            if ($key === false) {
                return new JsonResponse(['message' => 'failed to read private key'], 500);
            }
            $ok = openssl_sign($signingInput, $signature, $key, OPENSSL_ALGO_SHA256);
            if (!$ok) {
                return new JsonResponse(['message' => 'failed to sign token'], 500);
            }
        } else {
            if ($secret === '') {
                return new JsonResponse(['message' => 'missing DEMO_JWT_SECRET'], 500);
            }
            $signature = hash_hmac('sha256', $signingInput, $secret, true);
        }

        $jwt = $signingInput.'.'.$this->base64UrlEncode($signature);

        return new JsonResponse(['token' => $jwt, 'user_id' => $userId]);
    }

    #[Route('/api/demo/chat/send', name: 'demo_chat_send', methods: ['POST'])]
    public function sendChatMessage(
        Request $request,
        WebsocketPublisher $publisher,
        PresenceProviderInterface $presence
    ): JsonResponse {
        $data = json_decode($request->getContent(), true);
        $text = is_array($data) ? (string) ($data['text'] ?? '') : '';
        $user = is_array($data) ? (string) ($data['user'] ?? 'anon') : 'anon';
        if ($text === '') {
            return new JsonResponse(['ok' => false, 'message' => 'empty message'], 400);
        }

        $connections = $presence->listConnections();
        $targets = [];
        if (isset($connections['connections']) && is_array($connections['connections'])) {
            foreach ($connections['connections'] as $conn) {
                if (!is_array($conn)) {
                    continue;
                }
                $uid = $conn['user_id'] ?? null;
                if ($uid) {
                    $targets['user:'.$uid] = true;
                }
            }
        }

        if (empty($targets)) {
            $targets[$user] = true;
        }

        $payload = [
            'type' => 'chat',
            'user' => $user,
            'text' => $text,
            'ts' => time(),
        ];

        $publisher->send(array_keys($targets), $payload);

        return new JsonResponse(['ok' => true]);
    }

    private function base64UrlEncode(string $data): string
    {
        return rtrim(strtr(base64_encode($data), '+/', '-_'), '=');
    }
}
