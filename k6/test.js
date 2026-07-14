import http from 'k6/http';
import { check } from 'k6';
import { Rate } from 'k6/metrics';

const endpoint = __ENV.ENDPOINT || '/call/async-tuned';
const vu = parseInt(__ENV.VUS || '100', 10);
const dur = __ENV.DURATION || '20s';
const ramp = __ENV.RAMP || '5s';

const target = `http://api1:8000${endpoint}`;
const failRate = new Rate('failed_requests');

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
  noConnectionReuse: false,
  thresholds: {
    failed_requests: ['rate<0.05'],
  },
};

export default function () {
  const res = http.get(target, { timeout: '15s' });
  const ok = check(res, {
    'status 200': (r) => r.status === 200,
  });
  failRate.add(!ok);
}

// k6 の summary を JSON で書き出し、ホスト側 ./k6/results/<name>.json に保存する。
export function handleSummary(data) {
  const name = __ENV.OUT_NAME || 'summary';
  const out = {};
  out['/scripts/results/' + name + '.json'] = JSON.stringify(data, null, 2);
  out['stdout'] = textSummary(data);
  return out;
}

// 外部依存なしでコンパクトなテキストサマリーを作る。
function textSummary(data) {
  const m = data.metrics;
  const f = (v) => (v === undefined || v === null ? 'n/a' : v.toFixed(3));
  const fd = (v) => (v === undefined || v === null ? 'n/a' : v.toFixed(2));
  const lines = [];
  lines.push('==== k6 summary ====');
  lines.push('endpoint        : ' + endpoint);
  lines.push('target          : ' + target);
  lines.push('vus             : ' + vu);
  lines.push('http_reqs       : ' + m.http_reqs.values.count + ' (' + f(m.http_reqs.values.rate) + '/s)');
  lines.push('iteration count : ' + m.iterations.values.count);
  lines.push('http_req_duration');
  lines.push('  avg           : ' + fd(m.http_req_duration.values.avg) + ' ms');
  lines.push('  min           : ' + fd(m.http_req_duration.values.min) + ' ms');
  lines.push('  med(p50)      : ' + fd(m.http_req_duration.values['med']) + ' ms');
  lines.push('  p90           : ' + fd(m.http_req_duration.values['p(90)']) + ' ms');
  lines.push('  p95           : ' + fd(m.http_req_duration.values['p(95)']) + ' ms');
  lines.push('  max           : ' + fd(m.http_req_duration.values.max) + ' ms');
  lines.push('http_req_failed : ' + (m.http_req_failed.values.rate * 100).toFixed(2) + ' %');
  return lines.join('\n') + '\n';
}
