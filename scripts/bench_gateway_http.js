import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: __ENV.VUS ? parseInt(__ENV.VUS, 10) : 50,
  duration: __ENV.DURATION || '30s',
};

const base = __ENV.BASE_URL || 'http://host.docker.internal:8180';
const doPublish = (__ENV.PUBLISH || '1') === '1';
const apiKey = __ENV.API_KEY || 'dev-key';

export default function () {
  const health = http.get(`${base}/health`);
  check(health, { 'health 200': (r) => r.status === 200 });

  if (doPublish) {
    const payload = JSON.stringify({
      api_key: apiKey,
      subjects: ['user:1'],
      payload: { type: 'bench', ts: Date.now() },
    });
    const res = http.post(`${base}/internal/publish`, payload, {
      headers: { 'Content-Type': 'application/json' },
    });
    check(res, { 'publish 200': (r) => r.status === 200 });
  }

  sleep(0.1);
}
