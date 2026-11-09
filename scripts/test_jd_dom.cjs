/* Real browser parsing of synthetic DOM only; no account or JD network access. */
const fs = require('node:fs'), assert = require('node:assert/strict'), path = require('node:path');
const {chromium} = require(process.env.JOURNAL_PLAYWRIGHT || 'playwright');
const source = fs.readFileSync(path.join(__dirname, 'jd_adapter.py'), 'utf8');
const match = source.match(/LIST_PAGE_SCRIPT = r"""([\s\S]*?)"""/);
if (!match) throw new Error('JD list script not found');
const list = match[1], args = process.argv.slice(2), i = args.indexOf('--browser');
(async () => {
  const server = await chromium.launchServer({headless:true, ...(i < 0 ? {} : {executablePath:args[i + 1]})});
  const browser = await chromium.connect(server.wsEndpoint());
  const context = await browser.newContext({offline:true}), page = await context.newPage();
  let checks = 0;
  try {
    const row = (name = 'Synthetic pot', sku = '12345678') => `<div class="productItem-hash"><a class="goodImg-hash" href="https://item.jd.com/${sku}.html?pcdk=SECRET_TRACKING#trace"><img src="https://img10.360buyimg.com/n0/s500x500_jfs/synthetic.png"></a><h3 class="productTitle-hash">${name}</h3><span class="productCount-hash">共 1 件</span></div>`;
    const order = (n, split = false, status = '已完成') => `<div class="orderCard-hash"><div class="header-hash ${split ? 'splitOrderHeader-hash' : ''}"><div class="headerLeft-hash"><span class="orderTime-hash"><span class="metaValue-hash">2026-11-08 12:34:56</span></span><span class="orderMetas-hash">订单号：90000000000000000${n}</span><div class="shopInfo-hash"><span class="shopNames-hash">Synthetic shop</span></div></div><div class="headerRight-hash"><span class="rightStateStyle-hash"><span class="statusText-hash">${status}</span></span></div></div><div class="orderBody-hash">${row()}<div class="priceActionSection-hash"><div class="paymentTypestyle-hash"><div class="priceColumn-hash"><div class="priceRow-hash">¥ 22 . 90</div></div></div></div><div class="detailLink-hash"><span>订单详情</span></div><div class="deliveryAndExpress-hash">SECRET_PHONE_ADDRESS</div></div></div>`;
    const banner = `<div class="splitBanner-hash"><div class="metaSection-hash"><div class="infoGroup-hash">订单号<span class="metaValue-hash">900000000000000099</span></div><div class="infoGroup-hash">订单金额<span class="metaValue-hash">￥500.00</span></div></div></div>`;
    const pages = `<div class="pageNumbers-hash"><button class="prevBtn-hash" disabled>上一页</button><button class="pageItem-hash activePage-hash">1</button><button class="pageItem-hash">2</button><button class="nextBtn-hash">下一页</button></div>`;
    await page.setContent(`<select><option selected>近3个月订单</option></select><div class="listContent-hash">${order(1)}<div>${banner}<div>${order(2,true)}${order(3,true,'等待收货')}</div></div></div>${pages}<aside>${row('UNRELATED_RECOMMENDATION')}</aside>`);
    let data = JSON.parse(await page.evaluate(list));
    assert.equal(data.orders.length, 3); checks++;
    assert.equal(data.orders[0].rows.length, 1); checks++;
    assert.equal(data.orders[1].parent_order_id_text, '900000000000000099'); checks++;
    assert.equal(data.orders[0].parent_order_id_text, null); checks++;
    assert.equal(data.orders[1].is_split_order, true); checks++;
    assert.equal(data.orders[0].detail_url, null); checks++;
    assert.equal(data.orders[0].payment_text, '¥ 22 . 90'); checks++;
    assert.equal(data.orders[0].order_date, '2026-11-08 12:34:56'); checks++;
    assert.equal(data.orders[0].status, '已完成'); checks++;
    assert.equal(data.orders[2].status, '等待收货'); checks++;
    assert.equal(data.pagination.active, '1'); checks++;
    assert.equal(data.pagination.next_disabled, false); checks++;
    assert.equal(data.pagination.prev_disabled, true); checks++;
    assert.equal(data.selected_period, '近3个月订单'); checks++;
    await page.evaluate(() => {document.querySelector('select').remove(); const d = document.createElement('div'); d.className = 'select-observed'; d.innerHTML = '<span>2025年订单</span>'; document.body.prepend(d);});
    assert.equal(JSON.parse(await page.evaluate(list)).selected_period, '2025年订单'); checks++;
    assert.equal(data.route_status, 'ready'); checks++;
    assert(!JSON.stringify(data).includes('SECRET_PHONE_ADDRESS')); checks++;
    assert(!JSON.stringify(data).includes('UNRELATED_RECOMMENDATION')); checks++;
    assert(!JSON.stringify(data).includes('500.00')); checks++;
    assert(!JSON.stringify(data).includes('SECRET_TRACKING')); checks++;
    assert.equal(data.orders[0].rows[0].item_url, 'https://item.jd.com/12345678.html'); checks++;
    // Real split layout: later sibling wrapper does not contain the banner.
    await page.setContent(`<div class="listContent-hash"><div>${banner}<div>${order(2,true)}</div></div><div>${order(3,true)}</div><div>${order(4)}</div><div>${order(5,true)}</div></div>${pages}`);
    data = JSON.parse(await page.evaluate(list));
    assert.equal(data.orders[1].parent_order_id_text, '900000000000000099'); checks++;
    assert.equal(data.orders[2].parent_order_id_text, null); checks++;
    assert.equal(data.orders[3].parent_order_id_text, null); checks++;
    await page.setContent(`<div class="listContent-hash"><div>${order(2,true)}</div></div>${pages}`);
    assert.equal(JSON.parse(await page.evaluate(list)).orders[0].parent_order_id_text, null); checks++;
    await page.evaluate(() => {const a = document.querySelector('[class^="goodImg-"]'); a.querySelector('img').remove(); a.innerHTML = '<div class="lazyload-wrapper"><div class="lazyload-placeholder"></div></div>';});
    data = JSON.parse(await page.evaluate(list));
    assert.equal(data.orders[0].rows[0].image_url, null); checks++;
    assert.equal(data.orders[0].rows[0].image_pending, true); checks++;
    await page.evaluate(() => document.querySelector('[class^="nextBtn-"]').disabled = true);
    assert.equal(JSON.parse(await page.evaluate(list)).pagination.next_disabled, true); checks++;
    await page.evaluate(() => document.querySelector('[class^="nextBtn-"]').remove());
    assert.equal(JSON.parse(await page.evaluate(list)).pagination.next_disabled, null); checks++;
    await page.setContent('<input type="password">');
    assert.equal(JSON.parse(await page.evaluate(list)).route_status, 'login_required'); checks++;
    await page.setContent('<div role="alert">请完成验证码</div>');
    assert.equal(JSON.parse(await page.evaluate(list)).route_status, 'blocked'); checks++;
    await page.setContent('<div aria-busy="true">Loading</div>');
    assert.equal(JSON.parse(await page.evaluate(list)).route_status, 'loading'); checks++;
    await page.setContent('<div class="select-observed"><span>2016年订单</span></div><div class="listContent-hash"></div><div class="empty-observed">没有相关订单哦~去首页看看查看全部订单</div>');
    data = JSON.parse(await page.evaluate(list));
    assert.equal(data.route_status, 'empty'); checks++;
    assert.equal(data.selected_period, '2016年订单'); checks++;
    assert.equal(data.pagination.active, null); checks++;
    assert(data.empty_message.startsWith('没有相关订单哦')); checks++;
    await page.setContent('<div class="listContent-hash"></div>');
    assert.equal(JSON.parse(await page.evaluate(list)).route_status, 'empty_or_unrecognized'); checks++;
    console.log(JSON.stringify({ok:true,synthetic_dom_checks:checks,live_account_verified:false}));
  } catch (error) {
    console.error(error); process.exitCode = 1;
  } finally {
    await server.kill();
  }
})();
