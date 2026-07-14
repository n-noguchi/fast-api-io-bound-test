import http from 'k6/http';
import { check } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// /query (tenantid+date+dimension1 -> row group skip 可能) と
// /scan  (dimension1 のみ -> ほぼ全 row group スキャン) を切替えて pushdown 効果を比較
const endpoint = __ENV.ENDPOINT || '/query';
const vu = parseInt(__ENV.VUS || '20', 10);
const dur = __ENV.DURATION || '20s';
const ramp = __ENV.RAMP || '5s';

const target = `http://api1b:8000${endpoint}`;
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
  thresholds: {
    failed_requests: ['rate<0.05'],
  },
};

export default function () {
  let url;
  if (endpoint === '/scan') {
    url = `${target}?dimension1=cat_05&limit=100`;
  } else {
    // 単一 tenantid(1..1000) を VU ごとにずらす。GROUP BY 集計。
    const tenantid = ((__VU * 7 + __ITER) % 1000) + 1;
    url = `${target}?tenantid=${tenantid}&date_from=2000-01-01&date_to=2026-07-16`;
  }
  const res = http.get(url, { timeout: '30s' });
  const ok = check(res, { 'status 200': (r) => r.status === 200 });
  failRate.add(!ok);
  if (ok && res.timings) queryLatency.add(res.timings.waiting);
}

export function handleSummary(data) {
  const name = __ENV.OUT_NAME || 'df-summary';
  const out = {};
  out['/scripts/results/' + name + '.json'] = JSON.stringify(data, null, 2);
  out['stdout'] = textSummary(data);
  return out;
}

function textSummary(data) {
  const m = data.metrics;
  const f = (v) => (v === undefined || v === null ? 'n/a' : v.toFixed(3));
  const fd = (v) => (v === undefined || v === null ? 'n/a' : v.toFixed(2));
  const lines = [];
  lines.push('==== k6 summary (datafusion) ====');
  lines.push('endpoint        : ' + endpoint);
  lines.push('vus             : ' + vu);
  lines.push('http_reqs       : ' + m.http_reqs.values.count + ' (' + f(m.http_reqs.values.rate) + '/s)');
  lines.push('http_req_duration');
  lines.push('  avg           : ' + fd(m.http_req_duration.values.avg) + ' ms');
  lines.push('  med(p50)      : ' + fd(m.http_req_duration.values['med']) + ' ms');
  lines.push('  p90           : ' + fd(m.http_req_duration.values['p(90)']) + ' ms');
  lines.push('  p95           : ' + fd(m.http_req_duration.values['p(95)']) + ' ms');
  lines.push('  max           : ' + fd(m.http_req_duration.values.max) + ' ms');
  lines.push('http_req_failed : ' + (m.http_req_failed.values.rate * 100).toFixed(2) + ' %');
  return lines.join('\n') + '\n';
}
