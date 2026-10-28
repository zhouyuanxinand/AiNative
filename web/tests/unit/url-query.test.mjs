import assert from 'node:assert/strict';
import test from 'node:test';
import { urlWithQuery } from '../../src/shared/lib/url.ts';

const cases = [
  ['/admin', '', '/admin'],
  ['/admin', 'view=logs', '/admin?view=logs'],
  ['/admin', 'view=resources', '/admin?view=resources'],
  ['/admin', 'view=admins', '/admin?view=admins'],
  ['/admin', 'q=CY&rating=poor&page=2', '/admin?q=CY&rating=poor&page=2'],
  ['/admin', 'view=logs&q=CY&log_status=failed&log_request=request-1', '/admin?view=logs&q=CY&log_status=failed&log_request=request-1'],
  ['/api/logs/requests', 'status=failed&q=CY', '/api/logs/requests?status=failed&q=CY'],
  ['/api/logs/requests', '', '/api/logs/requests'],
];

for (const legacy of [false, true]) {
  test(`navigation and filter URLs ${legacy ? 'without' : 'with'} URLSearchParams.size`, () => {
    const size = Object.getOwnPropertyDescriptor(URLSearchParams.prototype, 'size');
    try {
      if (legacy) delete URLSearchParams.prototype.size;
      for (const [path, query, expected] of cases) {
        assert.equal(urlWithQuery(path, new URLSearchParams(query)), expected);
      }
      assert.equal(urlWithQuery('/admin', new URLSearchParams({ q: '反馈 & CY+1' })),
        '/admin?q=%E5%8F%8D%E9%A6%88+%26+CY%2B1');
    } finally {
      if (size) Object.defineProperty(URLSearchParams.prototype, 'size', size);
    }
  });
}
