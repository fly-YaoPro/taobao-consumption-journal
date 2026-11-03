/* Optional real DOM tests using synthetic HTML only. No Taobao/network access. */
const fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require(process.env.JOURNAL_PLAYWRIGHT||'playwright');
const source=fs.readFileSync(path.join(__dirname,'taobao_adapter.py'),'utf8');
const extract=name=>{const m=source.match(new RegExp(name+' = r"""([\\s\\S]*?)"""'));if(!m)throw Error('script not found');return m[1];};
const list=extract('LIST_PAGE_SCRIPT'),detail=extract('DETAIL_PAGE_SCRIPT');
const args=process.argv.slice(2),i=args.indexOf('--browser');
(async()=>{
 const server=await chromium.launchServer({headless:true,...(i<0?{}:{executablePath:args[i+1]})});
 const browser=await chromium.connect(server.wsEndpoint()),ctx=await browser.newContext({offline:true}),p=await ctx.newPage();
 let checks=0;
 try{
  const row=j=>`<div><div class="itemInfoColItem--hash"><a class="image--hash" style="background-image:url(https://img.example.test/${j}.jpg)"></a><a class="title--hash" href="https://item.example.test/"><span class="titleText--hash">Synthetic item ${j}</span></a><span class="infoContent--hash">test SKU</span></div><div class="itemInfoColPrice--hash">￥10x2</div></div>`;
  const order=n=>`<div class="trade-bought-list-order-container"><span class="shopInfoOrderTime--hash">2025-05-19</span><span class="shopInfoOrderId--hash">订单号:900000000000000${String(n).padStart(4,'0')}</span><span class="shopInfoStatus--hash">交易成功</span><a class="shopInfoOrderDetail--hash" href="https://trade.example.test/detail?biz_order_id=900000000000000${String(n).padStart(4,'0')}"></a><div class="orderPaymentCol--hash">实付款￥20.00</div>${row(n)}${n===1?row(100):''}</div>`;
  await p.setContent(`<div id="private-address">SECRET_ADDRESS_NOT_FOR_COLLECTION</div>${Array.from({length:30},(_,j)=>order(j+1)).join('')}<li class="ant-pagination-item ant-pagination-item-active" title="1"></li><li class="ant-pagination-next" aria-disabled="false"><button>Next</button></li>`);
  let data=JSON.parse(await p.evaluate(list));assert.equal(data.orders.length,30);checks++;
  assert.equal(data.orders[0].rows.length,2);checks++;
  assert.equal(data.pagination.next_disabled,false);checks++;
  assert.equal(data.route_status,'ready');checks++;
  assert(!JSON.stringify(data).includes('SECRET_ADDRESS'));checks++;
  await p.evaluate(()=>document.querySelector('.ant-pagination-next').setAttribute('aria-disabled','true'));
  assert.equal(JSON.parse(await p.evaluate(list)).pagination.next_disabled,true);checks++;
  await p.evaluate(()=>document.querySelector('.ant-pagination-next').remove());
  assert.equal(JSON.parse(await p.evaluate(list)).pagination.next_disabled,null);checks++;
  await p.setContent('<input type="password">');assert.equal(JSON.parse(await p.evaluate(list)).route_status,'login_required');checks++;
  await p.setContent('<div class="nc-container">请完成验证码</div>');assert.equal(JSON.parse(await p.evaluate(list)).route_status,'blocked');checks++;
  await p.setContent('<div class="ant-spin-spinning">Loading</div>');assert.equal(JSON.parse(await p.evaluate(list)).route_status,'loading');checks++;
  await p.setContent(`<div class="imageContainer"><a class="image--hash" style="background-image:url(https://img.example.test/genuine.jpg)"></a></div><img class="product-img" src="data:image/gif;base64,R0lGODlhAQABAAAAACw="><div class="detailInfoContent--hash">创建时间2025-05-19 12:30:00</div><div class="detailInfoContent--hash">实付款￥20.00</div>`);
  data=JSON.parse(await p.evaluate(detail));assert.equal(data.main_image,'https://img.example.test/genuine.jpg');checks++;
  assert.equal(data.times['创建时间'],'2025-05-19 12:30:00');assert.equal(data.amounts['实付款'],'20.00');checks++;
  console.log(JSON.stringify({ok:true,synthetic_dom_checks:checks,live_harness_verified:false}));
 }catch(e){console.error(e);process.exitCode=1;}finally{await server.kill();}
})();
