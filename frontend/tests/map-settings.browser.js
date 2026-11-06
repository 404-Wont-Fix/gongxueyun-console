// Run with an authenticated local preview:
// playwright-cli run-code --filename=frontend/tests/map-settings.browser.js
// Map configuration requests are mocked; never writes real settings.
async page => {
  const originalViewport = page.viewportSize();
  const url = 'http://127.0.0.1:8000/settings';
  const amap = {
    provider: 'amap', has_amap_key: false,
    geocode_base_url: 'https://nominatim.openstreetmap.org',
    tile_url: 'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
    tile_subdomains: '1234', tile_coord: 'gcj02', attribution: '© 高德地图', source: 'env',
  };
  let saved = { ...amap };
  let writes = 0;
  const errors = [];
  const onError = error => errors.push(error.message);
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const routeHandler = async route => {
    const req = route.request();
    if (req.method() === 'PUT') {
      writes++;
      const body = req.postDataJSON();
      saved = { ...saved, ...body, has_amap_key: !!body.amap_key || saved.has_amap_key, source: 'database' };
      delete saved.amap_key;
    } else if (req.method() === 'DELETE') {
      writes++;
      saved = { ...amap };
    }
    await route.fulfill({ json: saved });
  };
  page.on('pageerror', onError);
  await page.route('**/api/settings/map', routeHandler);
  try {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(url);
    const card = page.getByTestId('map-settings');
    const high = card.getByRole('button', { name: '高德（GCJ-02）', exact: true });
    const osm = card.getByRole('button', { name: 'OSM（WGS-84）', exact: true });
    const save = card.getByRole('button', { name: '保存地图配置', exact: true });
    await high.waitFor();
    assert(await high.getAttribute('aria-pressed') === 'true', 'Initial AMap selection');
    assert(await save.isDisabled(), 'Unchanged form must not be dirty');
    assert(await card.getByRole('button', { name: '测试地址搜索' }).isDisabled(), 'Missing key disables test');
    assert(!await card.locator('details').evaluate(el => el.open), 'Advanced settings collapsed');
    await card.screenshot({ path: 'map-restored-desktop.png' });

    await osm.click();
    assert(await card.locator('#map-provider').inputValue() === 'osm', 'Preset sets geocoder');
    assert((await card.locator('#map-url').inputValue()).includes('tile.openstreetmap.org'), 'Preset sets tiles');
    assert(await card.locator('#map-coord').inputValue() === 'wgs84', 'Preset sets coordinate system');
    assert(await card.locator('#map-key').isVisible(), 'Original layout always shows Key field');
    await card.locator('#map-provider').selectOption('amap');
    assert(await high.getAttribute('aria-pressed') === 'true', 'Dropdown switches tile highlight');
    assert(await card.locator('#map-coord').inputValue() === 'gcj02', 'Dropdown switches coordinate system');
    await card.locator('#map-provider').selectOption('osm');
    assert(await osm.getAttribute('aria-pressed') === 'true', 'Dropdown switches back to OSM');
    assert(writes === 0, 'Preset switch does not save automatically');
    await save.click();
    await page.waitForFunction(() => Array.from(document.querySelectorAll('[data-testid="map-settings"] button')).some(el => el.textContent.includes('保存地图配置') && el.disabled));
    await page.reload();
    await osm.waitFor();
    assert(await osm.getAttribute('aria-pressed') === 'true', 'OSM persists after reload');
    assert(await save.isDisabled(), 'Reload reflects saved form');

    await high.click();
    await card.locator('#map-key').fill('browser-fixture-key');
    await save.click();
    await page.waitForFunction(() => Array.from(document.querySelectorAll('[data-testid="map-settings"] button')).some(el => el.textContent.includes('保存地图配置') && el.disabled));
    await page.reload();
    await high.waitFor();
    assert(await high.getAttribute('aria-pressed') === 'true', 'AMap persists after reload');
    const masked = await card.locator('#map-key').inputValue();
    assert(masked.length >= 8 && masked.split('').every(ch => ch === '•'), `Saved key shows mask, got: ${masked}`);
    assert(!(await page.content()).includes('browser-fixture-key'), 'Real key never echoed');
    await card.locator('#map-key').focus();
    assert(await card.locator('#map-key').inputValue() === '', 'Focus clears mask for replacement');
    await card.locator('#map-key').blur();
    assert((await card.locator('#map-key').inputValue()).split('').every(ch => ch === '•'), 'Blur restores mask');
    assert(!await card.getByRole('button', { name: '测试地址搜索' }).isDisabled(), 'Saved key enables test');

    saved = { ...amap, provider: 'osm' };
    await page.reload();
    await high.waitFor();
    assert(await high.getAttribute('aria-pressed') === 'false', 'Mixed settings not mislabeled AMap');
    assert(await osm.getAttribute('aria-pressed') === 'false', 'Mixed settings not mislabeled OSM');
    assert(await card.locator('details').evaluate(el => el.open), 'Mixed settings visible in advanced');
    assert(await save.isDisabled(), 'Loading mixed settings does not mutate them');
    await high.click();
    assert(!await card.locator('details').evaluate(el => el.open), 'Selecting preset collapses advanced');
    await card.locator('summary').click();
    await card.locator('#map-coord').selectOption('wgs84');
    assert(await high.getAttribute('aria-pressed') === 'false', 'Coordinate override marks custom');
    await high.click();
    await page.setViewportSize({ width: 390, height: 844 });
    await card.scrollIntoViewIfNeeded();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Mobile layout must not overflow');
    await card.screenshot({ path: 'map-restored-mobile.png' });
    assert(errors.length === 0, `Browser errors: ${errors.join(', ')}`);
    return { passed: true, checks: 'presets, dirty state, mocked save/reload, key masking, mixed/custom config, mobile overflow', realSettingsChanged: false };
  } finally {
    await page.unroute('**/api/settings/map', routeHandler);
    page.off('pageerror', onError);
    if (originalViewport) await page.setViewportSize(originalViewport);
    await page.goto(url);
  }
}
