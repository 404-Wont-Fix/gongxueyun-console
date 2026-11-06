// Run with an authenticated local preview. All calendar/account writes are mocked.
// playwright-cli run-code --filename=frontend/tests/calendar.browser.js
async page => {
  // Use a fresh page so failed earlier scripts cannot leave stale route handlers.
  await page.unroute('**/api/calendar**');
  await page.unroute('**/api/accounts');
  page = await page.context().newPage();
  const assert = (v, message) => { if (!v) throw new Error(message); };
  const originalViewport = page.viewportSize();
  let override = null, overrideWrites = 0, recordQueries = 0;
  const account = { id: 901, label: '日历演示账号', auto_clock_in: true };
  const errors = [];
  const onError = e => errors.push(e.message);
  function fixture(month) {
    const [y, m] = month.split('-').map(Number);
    const days = Array.from({ length: new Date(y, m, 0).getDate() }, (_, i) => {
      const date = `${month}-${String(i + 1).padStart(2, '0')}`;
      const off = month === '2026-10' && i < 7;
      const makeup = month === '2026-10' && i === 9;
      const mode = override && date === '2026-10-01' ? override : off ? 'holiday' : 'work';
      return { date, weekday: ((new Date(y, m - 1, i + 1).getDay() + 6) % 7) + 1,
        day_type: off ? 'holiday' : makeup ? 'makeup' : 'normal', name: off || makeup ? '国庆节' : '', is_today: false,
        stats: { expected: mode === 'skip' ? 0 : mode === 'holiday' ? 1 : 2, confirmed: i === 0 ? 1 : 0, pending: i === 1 ? 1 : 0, failed: i === 2 ? 1 : 0, remaining: 1, attempts: i === 0 ? 1 : 0 },
        plans: [{ account_id: 901, account_label: account.label, mode, source: override && i === 0 ? 'override' : 'calendar', reason: '日历测试', automatic: true, slots: mode === 'skip' ? [] : mode === 'holiday' ? [{ kind: 'HOLIDAY', time: '08:30' }] : [{ kind: 'START', time: '08:30' }, { kind: 'END', time: '18:00' }] }],
        records: [], executions: i === 0 ? [{ id: 901, account_id: 901, account_label: account.label, kind: 'HOLIDAY', status: 'success', message: '模拟记录回查已确认', time: `${date}T00:30:00Z` }] : [] };
    });
    return { month, today: '2026-10-01', accounts: [account], days,
      stats: { expected: 55, confirmed: 1, pending: 1, failed: 1, attempts: 3 }, record_sync: [],
      calendar: { year: y, status: 'ready', has_cache: true, message: '三源日期核对一致', checked_at: '2026-10-01T00:00:00Z', accepted_at: '2026-10-01T00:00:00Z', sources: Object.fromEntries(['gov', 'holiday_cn', 'timor'].map(k => [k, { status: 'ok', urls: [], days: 39 }])) } };
  }
  const handler = async route => {
    const req = route.request(), rawUrl = req.url();
    const path = rawUrl.replace(/^https?:\/\/[^/]+/, '').split('?')[0];
    if (path === '/api/accounts') return route.fulfill({ json: [account] });
    if (path === '/api/calendar') return route.fulfill({ json: fixture(rawUrl.match(/[?&]month=([^&]+)/)[1]) });
    if (path.startsWith('/api/calendar/overrides/')) {
      overrideWrites++;
      override = req.method() === 'DELETE' ? null : req.postDataJSON().mode;
      return route.fulfill({ json: {} });
    }
    if (path.startsWith('/api/calendar/records/')) { recordQueries++; return route.fulfill({ json: {} }); }
    return route.fulfill({ json: fixture('2026-10').calendar });
  };
  await page.route('**/api/calendar**', handler);
  await page.route('**/api/accounts', handler);
  page.on('pageerror', onError);
  try {
    await page.setViewportSize({ width: 1280, height: 980 });
    await page.goto('http://127.0.0.1:8000/calendar');
    await page.getByLabel('选择月份').fill('2026-10');
    const oct1 = page.getByRole('button', { name: /^2026-10-01 / });
    await oct1.waitFor();
    assert(await page.locator('.calendar-day').count() === 31, 'October has 31 cells');
    assert(await page.locator('.day-tag.holiday').count() === 7, 'National Day has 7 rest days');
    assert(await page.locator('.day-tag.makeup').count() === 1, 'Oct 10 is makeup workday');
    await oct1.click();
    assert(await page.getByTestId('calendar-detail').getByText('模拟记录回查已确认').isVisible(), 'Selected day shows execution');
    assert(await page.getByRole('button', { name: '自定义当天安排' }).isDisabled(), 'All accounts cannot be overwritten together');
    await page.locator('#calendar-account').selectOption('901');
    await oct1.waitFor();
    await page.getByRole('button', { name: '自定义当天安排' }).click();
    await page.locator('#override-mode').selectOption('skip');
    await page.getByRole('button', { name: '保存当天安排' }).click();
    await page.waitForFunction(() => !document.querySelector('#override-mode'));
    assert(overrideWrites === 1 && override === 'skip', 'One mocked override write');
    await page.getByRole('button', { name: '同步该账号工学云记录' }).click();
    await page.waitForFunction(() => document.body.innerText.includes('记录已同步'));
    assert(recordQueries === 1, 'Record sync is explicit');
    await page.getByRole('button', { name: '自定义当天安排' }).click();
    await page.getByRole('button', { name: '恢复自动规则' }).click();
    await page.waitForFunction(() => !document.querySelector('#override-mode'));
    assert(override === null, 'Reset removes override');
    await page.locator('.toast').first().waitFor({ state: 'hidden' });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: 'calendar-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.querySelector('.sidebar').getBoundingClientRect().right <= 0);
    await page.evaluate(() => window.scrollTo(0, 0));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'No horizontal overflow on mobile');
    await page.screenshot({ path: 'calendar-mobile.png', fullPage: true });
    assert(errors.length === 0, errors.join('\n'));
    return { passed: true, checks: 'month cells, holiday/makeup markers, day detail, scoped override/reset, explicit record sync, mobile overflow', realSettingsChanged: false };
  } finally {
    await page.unroute('**/api/calendar**', handler);
    await page.unroute('**/api/accounts', handler);
    page.off('pageerror', onError);
    if (originalViewport) await page.setViewportSize(originalViewport);
    await page.close();
  }
}
