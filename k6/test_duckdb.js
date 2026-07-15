import http from 'k6/http';
import { check } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// api1b(DataFusion) の test_datafusion.js と同じクエリ・負荷形状で比較する。
const endpoint = __ENV.ENDPOINT || '/query';
const vu = parseInt(__ENV.VUS || '20', 10);
const dur = __ENV.DURATION || '20s';
const ramp = __ENV.RAMP || '5s';

const target = `http://api1c:8000${endpoint}`;
const failRate = new Rate('failed_requests');
const queryLatency = new Trend('query_latency', true);

export const options = {
  scenarios: {
    load: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: ramp, target: vu },
        { duration: dur, target: vu },
        { duration: ramp, target: 0 },
      ],
      gracefulRampDown: '5s',
    },
  },
  thresholds: { failed_requests: ['rate<0.05'] },
};

export default function () {
  let url;
  if (endpoint === '/scan') {
    url = `${target}?dimension1=cat_05&limit=100`;
  } else {
    const tenantid = ((__VU * 7 + __ITER) % 1000) + 1;
    url = `${target}?tenantid=${tenantid}&date_from=2000-01-01&date_to=2026-07-16`;
  }
  const res = http.get(url, { timeout: '30s' });
  const ok = check(res, { 'status 200': (r) => r.status === 200 });
  failRate.add(!ok);
  if (ok && res.timings) queryLatency.add(res.timings.waiting);
}

export function handleSummary(data) {
  const name = __ENV.OUT_NAME || 'duckdb-summary';
  return {
    [`/scripts/results/${name}.json`]: JSON.stringify(data, null, 2),
    stdout: textSummary(data),
  };
}

function textSummary(data) {
  const m = data.metrics;
  const f = (v) => (v === undefined || v === null ? 'n/a' : v.toFixed(3));
  const fd = (v) => (v === undefined || v === null ? 'n/a' : v.toFixed(2));
  return [
    '==== k6 summary (duckdb) ====',
    `endpoint        : ${endpoint}`,
    `vus             : ${vu}`,
    `http_reqs       : ${m.http_reqs.values.count} (${f(m.http_reqs.values.rate)}/s)`,
    'http_req_duration',
    `  avg           : ${fd(m.http_req_duration.values.avg)} ms`,
    `  med(p50)      : ${fd(m.http_req_duration.values.med)} ms`,
    `  p90           : ${fd(m.http_req_duration.values['p(90)'])} ms`,
    `  p95           : ${fd(m.http_req_duration.values['p(95)'])} ms`,
    `  max           : ${fd(m.http_req_duration.values.max)} ms`,
    `http_req_failed : ${(m.http_req_failed.values.rate * 100).toFixed(2)} %`,
  ].join('\n') + '\n';
}
