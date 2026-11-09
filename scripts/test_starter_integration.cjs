/* Real starter -> offline Chromium -> UI PNG download -> unchanged final checker.
 * Test-only synthetic orders; no account, platform requests or real user data.
 * Optional test dependency: npm install --no-save playwright
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.JOURNAL_PLAYWRIGHT || 'playwright');

const args = process.argv.slice(2);
function option(name) {
  const i = args.indexOf(name);
  if (i < 0) return undefined;
  assert(args[i + 1] && !args[i + 1].startsWith('--'), `${name} needs a value`);
  return args[i + 1];
}
const specified = option('--artifacts');
const kind = option('--kind') || 'taobao';
assert(['taobao', 'jd'].includes(kind), '--kind must be taobao or jd');
const root = specified ? path.resolve(specified) : fs.mkdtempSync(path.join(os.tmpdir(), 'journal-starter-'));
if (specified) {
  assert(!fs.existsSync(root) || fs.readdirSync(root).length === 0, 'Use a new/empty artifacts directory');
  fs.mkdirSync(root, { recursive: true });
}
const repo = path.resolve(__dirname, '..');
const source = path.join(root, 'synthetic-source');
const output = path.join(root, 'journal');
const python = process.env.JOURNAL_PYTHON || 'python';
function py(args) {
  const result = spawnSync(python, ['-X', 'utf8', '-B', ...args], {
    cwd: repo, encoding: 'utf8', env: { ...process.env, PYTHONUTF8: '1' }
  });
  if (result.error) throw result.error;
  assert.equal(result.signal, null, result.stderr);
  return result;
}
function finalCheck() {
  const result = py(['scripts/check_project.py', output, '--kind', kind, '--stage', 'final']);
  return { exit_code: result.status, ...JSON.parse(result.stdout) };
}
function rejected(report, fragment) {
  assert.equal(report.ok, false, JSON.stringify(report));
  assert.equal(report.exit_code, 1, JSON.stringify(report));
  assert(report.errors.some(e => e.includes(fragment)), JSON.stringify(report));
}

(async () => {
  let server;
  const receipt = { synthetic_only: true, kind, starter: 'assets/starter', offline: true };
  try {
    const fixture = py(['-c', kind === 'jd' ? `
import sys
sys.path.insert(0, 'scripts')
from test_jd_engine import jd_fixture
jd_fixture(sys.argv[1])
` : `
import sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from test_check_project import fixture, put
root=Path(sys.argv[1]); root.mkdir(parents=True)
fixture(root, 'taobao')
import json
meta=json.loads((root/'project_meta.json').read_text('utf-8'))
meta.update(title='虚构集成回归手账', synthetic_demo=True)
put(root, 'project_meta.json', meta)
put(root, 'story.json', {
  'overview': {'headline':'虚构测试的一页', 'text':'仅用于离线构建与导出回归，不是真实购物经历。', 'source_ids':['sample-order'], 'image_paths':[]},
  'themes':[{'id':'t1','title':'合成记录','text':'本夹具未提供商品图，只验证真实模板到浏览器PNG下载的链路。','source_ids':['sample-order'],'image_paths':[],'layout':'C'}],
  'findings':[{'title':'测试发现','text':'一条模拟订单含两件测试商品。','source_ids':['sample-order']}],
  'plans':[{'id':'p1','title':'核对测试导出','reason':'检查本次合成记录的导出链路。','source_ids':['sample-order'],'month':'','done':False}]
})
`, source]);
    assert.equal(fixture.status, 0, fixture.stderr);
    const built = py(['scripts/build_journal.py', '--source', source, '--output', output, '--skin', 'collage']);
    assert.equal(built.status, 0, built.stderr);
    receipt.build = JSON.parse(built.stdout);
    // Do not patch generated HTML or insert a hand-made PNG to get acceptance.
    const htmlPath = path.join(output, 'index.html');
    const html = fs.readFileSync(htmlPath, 'utf8');
    assert.equal(html, fs.readFileSync(path.join(repo, 'assets/starter/index.html'), 'utf8'));
    receipt.before_export = finalCheck();
    rejected(receipt.before_export, 'exports: no 1080x1440 PNG');

    server = await chromium.launchServer({ headless: true,
      ...(option('--browser') ? { executablePath: option('--browser') } : {}) });
    const browser = await chromium.connect(server.wsEndpoint());
    const context = await browser.newContext({ offline: true, acceptDownloads: true, viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const pageErrors = [];
    const remoteRequests = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    page.on('request', request => { if (/^https?:/i.test(request.url())) remoteRequests.push(request.url()); });
    await page.goto(pathToFileURL(htmlPath).href);
    await page.locator('#spread').waitFor({ state: 'visible' });
    await page.evaluate(() => document.fonts.ready);
    if (kind === 'jd') {
      assert.equal(await page.evaluate(() => window.JOURNAL_DATA.meta.platform), 'jd');
      assert.equal(await page.evaluate(() => window.JOURNAL_DATA.share_images.length), 1);
      await page.waitForFunction(() => [...document.querySelectorAll('#spread img')].some(im => im.complete && im.naturalWidth > 0));
      await page.locator('[data-view="calendar"]:visible').first().click();
      assert.equal(await page.locator('#year').inputValue(), '2026');
      assert.equal(await page.locator('#month').inputValue(), '08');
      await page.locator('#days button[data-populated="true"]').click();
      assert.equal(await page.locator('#day-detail .record-card').count(), 1);
      assert.equal(await page.locator('#category-label').isVisible(), true);
      await page.locator('#category').selectOption('居家');
      assert.equal(await page.locator('#search-results .record-card').count(), 1);
      assert((await page.locator('#search-results').innerText()).includes('2025-05-19'), 'Category search must include older years');
      await page.screenshot({ path: path.join(root, 'calendar-category.png'), fullPage: true });
      await page.locator('[data-view="plans"]:visible').first().click();
      assert.equal(await page.locator('#plan-list .plan-card').count(), 1, 'Auto-authored plan must be present');
      await page.locator('#plan-list').getByRole('button', { name: '编辑', exact: true }).click();
      await page.getByLabel('要做什么', { exact: true }).fill('合成测试：手动修改保留');
      await page.getByRole('button', { name: '保存', exact: true }).click();
      await page.reload();
      assert((await page.locator('#plan-list').innerText()).includes('合成测试：手动修改保留'), 'JD manual plan must survive reload');
      await page.locator('#plan-list').getByRole('button', { name: '标记完成', exact: true }).click();
      assert.equal(await page.locator('#plan-list .plan-card[data-done="true"]').count(), 1);
      await page.screenshot({ path: path.join(root, 'plans.png'), fullPage: true });
      await page.locator('[data-view="review"]:visible').first().click();
      receipt.jd_functional_checks = { real_local_fixture_image_loaded: true, default_populated_month: true,
        category_search_across_years: true, generated_plan: true, manual_plan_survives_reload: true, checkoff: true };
    }
    await page.locator('#share-button').click();
    const canvas = page.locator('#modal canvas');
    await canvas.waitFor({ state: 'visible' });
    receipt.canvas = await canvas.evaluate(c => {
      const ctx = c.getContext('2d');
      const colors = new Set();
      for (let y = 0; y < c.height; y += 37) for (let x = 0; x < c.width; x += 29)
        colors.add([...ctx.getImageData(x, y, 1, 1).data].join(','));
      return { width: c.width, height: c.height, sampled_colors: colors.size };
    });
    assert.equal(receipt.canvas.width, 1080);
    assert.equal(receipt.canvas.height, 1440);
    assert(receipt.canvas.sampled_colors > 3, 'Share canvas is blank');
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: '下载分享图 PNG', exact: true }).click()
    ]);
    assert.equal(await download.failure(), null);
    const pngPath = path.join(output, 'exports', 'share.png');
    await download.saveAs(pngPath);
    const png = fs.readFileSync(pngPath);
    assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    assert.deepEqual([png.readUInt32BE(16), png.readUInt32BE(20)], [1080, 1440]);
    assert(png.length > 3000, 'Downloaded PNG unexpectedly small');
    await page.screenshot({ path: path.join(root, 'share-preview.png') });
    await page.locator('#close-modal').click();
    await page.screenshot({ path: path.join(root, 'homepage.png'), fullPage: true });
    assert.deepEqual(pageErrors, [], 'Browser runtime errors');
    assert.deepEqual(remoteRequests, [], 'Offline template requested a network resource');
    receipt.png = { relative_path: 'journal/exports/share.png', bytes: png.length, width: 1080, height: 1440 };
    receipt.final = finalCheck();
    assert.equal(receipt.final.ok, true, JSON.stringify(receipt.final));
    assert.equal(receipt.final.exit_code, 0);

    // Negative controls: keep the strict scanner intact, including its existing
    // rejection of data: link resources, external scripts and missing assets.
    receipt.negative_controls = {};
    for (const [name, injection] of Object.entries({
      empty_data_icon: '<link rel="icon" href="data:,">',
      external_script: '<script src="https://example.invalid/not-local.js"></script>',
      missing_asset: '<link rel="stylesheet" href="missing-regression.css">'
    })) {
      try {
        fs.writeFileSync(htmlPath, html.replace('</head>', injection + '</head>'));
        const report = finalCheck();
        rejected(report, 'index.html');
        receipt.negative_controls[name] = report;
      } finally { fs.writeFileSync(htmlPath, html); }
    }
    receipt.restored_final = finalCheck();
    assert.equal(receipt.restored_final.ok, true, JSON.stringify(receipt.restored_final));
    assert.equal(receipt.restored_final.exit_code, 0);
    receipt.ok = true;
    console.log(JSON.stringify({ ok: true, artifacts: root, final: receipt.final,
      downloaded_png: receipt.png, negative_controls: Object.keys(receipt.negative_controls) }, null, 2));
  } catch (error) {
    receipt.ok = false;
    receipt.error = error.stack;
    console.error(error);
    process.exitCode = 1;
  } finally {
    if (server) await server.kill();
    fs.writeFileSync(path.join(root, 'integration-receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
  }
})();
