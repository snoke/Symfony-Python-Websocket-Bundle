import ws from 'k6/ws';
import { check, sleep } from 'k6';

export const options = {
  vus: __ENV.VUS ? parseInt(__ENV.VUS, 10) : 50,
  duration: __ENV.DURATION || '30s',
};

const wsUrl = __ENV.WS_URL || 'ws://host.docker.internal:8180/ws';
const token = __ENV.JWT || '';
const payloadBytes = __ENV.PAYLOAD_BYTES ? parseInt(__ENV.PAYLOAD_BYTES, 10) : 65536;
const messageCount = __ENV.MSG_COUNT ? parseInt(__ENV.MSG_COUNT, 10) : 1;
const sessionMs = __ENV.SESSION_MS ? parseInt(__ENV.SESSION_MS, 10) : 1000;
const payload = payloadBytes > 0 ? 'x'.repeat(payloadBytes) : '';

export default function () {
  const url = token ? `${wsUrl}?token=${token}` : wsUrl;
  const res = ws.connect(url, {}, (socket) => {
    socket.on('open', () => {
      const message = JSON.stringify({ type: 'ping', payload });
      for (let i = 0; i < messageCount; i += 1) {
        socket.send(message);
      }
      socket.setTimeout(() => socket.close(), sessionMs);
    });
    socket.on('error', () => {});
  });
  check(res, { 'ws connected': (r) => r && r.status === 101 });
  sleep(1);
}
