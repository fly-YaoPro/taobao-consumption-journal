/* Offline runtime. No fetch, CDN, remote model, or executable source content. */
(()=>{
  'use strict';
  const D=window.JOURNAL_DATA,C=window.JournalCore,$=s=>document.querySelector(s);
  if(!D||!C){document.body.textContent='数据文件未加载，请保留完整文件夹，不要只复制 index.html。';return;}
  if(D.skin==='collage'&&!window.JournalScrapbook){document.body.textContent='拼贴框架未加载，请保留 scrapbook.js、scrapbook.css 和 fonts/，不要只复制 index.html。';return;}
  const records=D.records,byId=new Map(records.map(r=>[r.id,r])),days=new Map();
  records.forEach(r=>{if(!days.has(r.date))days.set(r.date,[]);days.get(r.date).push(r);});
  const pages=[{...D.story.overview,id:'overview',title:D.story.overview.headline||D.meta.title},...D.story.themes];
  const key=`journal-v2:${D.project_key}`,keyPlans=`${key}:plans`,keyBackup=`${key}:pre-import`;
  let storageAvailable=true;
  function read(k,fallback){try{const raw=localStorage.getItem(k);return raw===null?fallback:JSON.parse(raw);}catch(e){storageAvailable=false;return fallback;}}
  function save(k,v){try{localStorage.setItem(k,JSON.stringify(v));return true;}catch(e){storageAvailable=false;notify('浏览器未能保存，请使用“备份计划”下载文件。');return false;}}
  const initial=read(key,{page:0}),stored=read(keyPlans,null);
  let page=Number.isInteger(initial.page)?Math.min(Math.max(0,initial.page),pages.length-1):0;
  let plans=C.validPlans(stored)?stored:D.story.plans.map(p=>({...p,done:!!p.done,note:p.note||'',origin:'suggestion'}));
  let currentMonth=records.length?records[records.length-1].date.slice(0,7):D.meta.requested_range.end.slice(0,7);
  let selectedDay=records.length?records[records.length-1].date:currentMonth+'-01',returnPage=null,activeView='review',searchPage=0,reviewScroll=0;
  let noticeTimer;
  function node(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!=null)el.textContent=text;return el;}
  function button(text,fn,cls){const b=node('button',cls,text);b.type='button';b.addEventListener('click',fn);return b;}
  function notify(text){$('#notice').textContent=text;$('#notice').hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$('#notice').hidden=true,4000);}
  function link(text,url){const a=node('a','',text);if(/^https?:\/\//i.test(url||'')){a.href=url;a.target='_blank';a.rel='noopener noreferrer';}else a.removeAttribute('href');return a;}
  function image(src,alt,cls){const img=node('img',cls);img.src=src;img.alt=alt;img.loading='lazy';img.addEventListener('error',()=>img.replaceWith(node('div','missing-photo','图片未能加载，原文仍可查看')),{once:true});return img;}
  function showModal(title,content){const d=$('#modal');$('#modal-title').textContent=title;$('#modal-content').replaceChildren(content);if(!d.open)d.showModal();}
  $('#close-modal').onclick=()=>$('#modal').close();$('#modal').addEventListener('click',e=>{if(e.target===$('#modal'))$('#modal').close();});
  function photo(asset,index=0){const f=node('figure','photo');if(asset){f.append(button('',()=>showModal(asset.caption||asset.date,image(asset.large||asset.path,asset.caption||'真实记录图片','lightbox-image'))));f.firstChild.setAttribute('aria-label','放大图片：'+(asset.caption||asset.date));f.firstChild.append(image(asset.path,asset.caption||'真实记录图片'));const caption=node('figcaption');caption.append(node('span','',asset.caption||''),node('time','',asset.date||''));f.append(caption);}else f.append(node('div','missing-photo','这段记录没有可用图片，保留真实文字。'));return f;}
  function assets(p){if(Array.isArray(p.images))return p.images;return (p.source_ids||[]).flatMap(id=>{const r=byId.get(id);return r?r.images.map(im=>({...im,date:r.date,caption:im.caption||r.title,record_id:r.id})):[];}).slice(0,3);}
  function textPhoto(p){const r=byId.get(p.source_ids?.[0]),w=node('div','text-memory');w.append(node('p','eyebrow',r?.date||'原文片段'),node('blockquote','quote',(r?.text||p.text).slice(0,160)),sources(r?[r.id]:p.source_ids));return w;}
  function sources(ids){const wrap=node('div','source-chips'),valid=[...new Set(ids||[])].filter(id=>byId.has(id));function go(id){const r=byId.get(id);returnPage=page;selectedDay=r.date;currentMonth=r.date.slice(0,7);$('#search').value='';$('#category').value='all';switchView('calendar');renderCalendar(id);$('#day-detail').scrollIntoView({block:'nearest'});}valid.slice(0,2).forEach(id=>{const r=byId.get(id);wrap.append(button(r.date+' · '+r.title.slice(0,6),()=>go(id)));});if(valid.length>2)wrap.append(button(`全部${valid.length}条来源`,()=>{const list=node('div','directory');valid.forEach(id=>{const r=byId.get(id);list.append(button(r.date+' · '+r.title,()=>{$('#modal').close();go(id);}));});showModal('回查来源',list);}));return wrap;}
  function song(){if(!D.story.song)return null;const s=D.story.song,w=node('div','song'),t=node('div');w.append(node('span','disc'));t.append(link(s.name+' · '+s.artist,s.url),node('p','',s.is_recommendation?'给这段记录推荐一首歌':'来自已核对记录的歌曲'),node('p','reason',s.reason));w.append(t);return w;}
  function timeline(){const w=node('div','timeline');(D.story.milestones||D.story.themes.slice(0,3).map(t=>({title:t.title,text:t.text,source_ids:t.source_ids}))).slice(0,4).forEach(m=>{const r=byId.get((m.source_ids||[])[0]);if(!r)return;const row=node('div','timeline-row');row.append(node('time','',r.date.slice(0,4)));const im=r.images[0];row.append(im?image(im.path,im.caption||r.title):node('span','text-marker',r.date.slice(5,7)));const copy=node('div');copy.append(node('h3','',m.title),node('p','',m.text||r.text.slice(0,60)));row.append(copy);w.append(row);});return w;}
  function spine(){const s=node('div','spine');for(let i=0;i<6;i++)s.append(node('i','ring'));s.setAttribute('aria-hidden','true');return s;}
  function addSticker(leaf){const s=node('span','sticker');s.setAttribute('aria-hidden','true');s.innerHTML='<svg viewBox="0 0 40 40" fill="none"><path d="M20 3v6m0 22v6M3 20h6m22 0h6M8 8l5 5m14 14 5 5M8 32l5-5M27 13l5-5" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/><circle cx="20" cy="20" r="7" stroke="currentColor" stroke-width="2"/></svg>';leaf.append(s);}
  function renderReview(){
    const host=$('#spread'),p=pages[page],im=assets(p);host.replaceChildren();
    if(D.skin==='collage'&&window.JournalScrapbook){window.JournalScrapbook.render({host,p,page,pages,D,records,byId,photo,sources,song,button,node,assets,plans,go:i=>{page=Math.max(0,Math.min(pages.length-1,i));renderReview();if(page===0)window.scrollTo({top:0,behavior:'instant'});else $('#spread').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});},view:switchView});
    }else{
      const layout=page===0?'A':p.layout||'A',book=node('article',`book theme-${layout}`),left=node('div','leaf'),right=node('div','leaf editorial');
      right.append(node('p','ribbon',page===0?'回看 · '+D.meta.title:'片段 '+String(page).padStart(2,'0')),node('h1','',p.headline||p.title),node('p','muted',p.range||''),node('p','lead',p.text),sources(p.source_ids));addSticker(right);
      if(page===0){left.append(im[0]?photo(im[0]):textPhoto(p));if(p.note)left.append(node('p','journal-note',p.note));const music=song();if(music)left.append(music);right.append(timeline());book.append(left,spine(),right);}
      else if(layout==='B'){
        const leaf=node('div','leaf compare-leaf'),copy=node('div','compare-text'),head=node('div');head.append(node('p','eyebrow',p.range||'前后翻一翻'),node('h1','',p.title));const body=node('div');body.append(node('p','lead',p.text),sources(p.source_ids));copy.append(head,body);const pair=node('div','compare-pair');im.slice(0,2).forEach(x=>pair.append(photo(x)));if(!im.length)p.source_ids.slice(0,2).forEach(id=>pair.append(textPhoto({source_ids:[id]})));leaf.append(copy,pair);book.append(leaf);
      }else if(layout==='C'){left.append(node('blockquote','quote',p.excerpt||p.text),sources(p.excerpt_source_ids||p.source_ids));right.append(photo(im[0]));book.append(left,spine(),right);}
      else{left.append(im[0]?photo(im[0]):textPhoto(p));if(p.note)left.append(node('p','journal-note',p.note));book.append(left,spine(),right);}
      if(page===0&&!im.length){book.replaceChildren(right);book.classList.add('text-only');right.append(node('p','source-note','没有可用图片的片段按原文整理，不补画历史照片。'));}host.append(book);
    }
    const pager=$('#pager'),prev=button('← 上一页',()=>turn(-1)),next=button('下一页 →',()=>turn(1));prev.disabled=page===0;next.disabled=page===pages.length-1;pager.replaceChildren(prev,button('目录',directory),node('span','',`${page+1} / ${pages.length}`),next);pager.hidden=D.skin==='collage'&&page===0;save(key,{page});
  }
  function turn(delta){page=Math.max(0,Math.min(pages.length-1,page+delta));renderReview();$('#spread').scrollIntoView({block:'start'});}
  function directory(){const d=node('div','directory');pages.forEach((p,i)=>d.append(button(`${String(i+1).padStart(2,'0')} / ${p.title}`,()=>{page=i;renderReview();$('#modal').close();$('#spread').scrollIntoView({block:'start'});})));showModal('目录',d);}
  function switchView(view){if(!['review','calendar','plans'].includes(view))view='review';if(activeView==='review'&&view!=='review')reviewScroll=window.scrollY;activeView=view;for(const id of ['review','calendar','plans'])$('#'+id).hidden=id!==view;document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-current',b.dataset.view===view?'page':'false'));if(view==='calendar')renderCalendar();if(view==='plans')renderPlans();if(location.hash!=='#'+view)history.replaceState(null,'','#'+view);window.scrollTo({top:view==='review'?reviewScroll:0,behavior:'instant'});if(view==='review')requestAnimationFrame(()=>window.scrollTo({top:reviewScroll,behavior:'instant'}));}
  document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>switchView(b.dataset.view));$('.brand').onclick=e=>{e.preventDefault();switchView('review');};
  function option(value,label){const o=node('option','',label);o.value=value;return o;}
  const years=[...new Set([...D.coverage.map(c=>Number(c.year)),...records.map(r=>Number(r.date.slice(0,4)))])].sort((a,b)=>a-b);years.forEach(y=>$('#year').append(option(y,y+'年')));for(let i=1;i<=12;i++)$('#month').append(option(String(i).padStart(2,'0'),i+'月'));
  function setMonth(ym){currentMonth=ym;const first=[...days.keys()].filter(d=>d.startsWith(ym)).sort()[0];selectedDay=first||ym+'-01';returnPage=null;renderCalendar();}
  function moveMonth(n){const [y,m]=currentMonth.split('-').map(Number),date=new Date(Date.UTC(y,m-1+n,1)),ym=date.toISOString().slice(0,7);if(Number(ym.slice(0,4))<years[0]||Number(ym.slice(0,4))>years[years.length-1])return;setMonth(ym);}
  $('#previous-month').onclick=()=>moveMonth(-1);$('#next-month').onclick=()=>moveMonth(1);$('#year').onchange=()=>setMonth($('#year').value+'-'+$('#month').value);$('#month').onchange=()=>setMonth($('#year').value+'-'+$('#month').value);
  function renderCalendar(target){
    const [year,month]=currentMonth.split('-').map(Number);$('#year').value=String(year);$('#month').value=String(month).padStart(2,'0');const strip=$('#months-strip');strip.replaceChildren();for(let m=1;m<=12;m++){const ym=`${year}-${String(m).padStart(2,'0')}`,count=records.filter(r=>r.date.startsWith(ym)).length,b=button(`${m}月${count?' ·':''}`,()=>setMonth(ym));b.dataset.active=ym===currentMonth;b.dataset.count=String(count);b.setAttribute('aria-label',`${m}月，${count}条已收录`);strip.append(b);}
    const monthRecords=records.filter(r=>r.date.startsWith(currentMonth));$('#month-note').textContent=`${year}年${month}月 · ${monthRecords.length}条已收录${D.meta.mode==='selected'?' · 精选样本':''}`;
    $('#previous-month').disabled=currentMonth<=`${years[0]}-01`;$('#next-month').disabled=currentMonth>=`${years[years.length-1]}-12`;
    const grid=$('#days');grid.replaceChildren();C.monthDays(year,month).forEach(day=>{if(!day){grid.append(node('span'));return;}const rs=days.get(day)||[],b=button('',()=>{selectedDay=day;renderCalendar();});b.dataset.populated=!!rs.length;b.dataset.selected=day===selectedDay;b.setAttribute('aria-label',`${day}，${rs.length}条已收录`);b.append(node('span','',String(Number(day.slice(-2)))));if(rs.length){b.append(node('span','day-count',String(rs.length)));const r=rs.find(r=>r.images.length)||rs[0];if(r.images[0])b.append(image(r.images[0].path,r.title));b.append(node('small','',r.title.slice(0,14)));}grid.append(b);});
    const detail=$('#day-detail');detail.replaceChildren(node('p','eyebrow','这一天'),node('h2','',selectedDay));if(returnPage!==null)detail.append(button('← 返回刚才的主题',()=>{page=returnPage;returnPage=null;switchView('review');renderReview();}));const rs=days.get(selectedDay)||[];if(!rs.length)detail.append(node('p','empty',C.scopeStatus(selectedDay,D.coverage)));else rs.forEach(r=>detail.append(recordCard(r,r.id===target)));renderSearch();
  }
  function recordCard(r,highlight=false){const w=node('article','record-card'+(highlight?' target':''));w.dataset.recordId=r.id;w.append(node('time','',r.date),node('h3','',r.title));if(r.images[0]){const im=r.images[0],b=button('',()=>showModal(r.title,image(im.large||im.path,im.caption||r.title,'lightbox-image')));b.setAttribute('aria-label','放大图片：'+r.title);b.append(image(im.path,im.caption||r.title,'record-image'));w.append(b);}const text=r.text||'';if(text.length>320){w.append(node('p','',text.slice(0,180)+'…'));const details=node('details'),summary=node('summary','','展开全文');details.append(summary,node('p','',text));w.append(details);}else w.append(node('p','',text));if(r.images.length>1){const details=node('details'),summary=node('summary','',`查看全部 ${r.images.length} 张图片`),row=node('div','compare-pair');r.images.forEach(im=>row.append(photo({...im,date:r.date,caption:im.caption||r.title})));details.append(summary,row);w.append(details);}const actions=node('div','record-actions');if(r.url)actions.append(link('查看平台原文',r.url));if(r.links)r.links.forEach(l=>actions.append(link(l.label||'正文链接',l.href)));if(activeView==='calendar'&&$('#search').value.trim())actions.append(button('定位这一天',()=>{$('#search').value='';selectedDay=r.date;currentMonth=r.date.slice(0,7);renderCalendar(r.id);}));w.append(actions);return w;}
  function renderSearch(){const query=$('#search').value.trim(),category=$('#category').value,filtered=!!query||category!=='all',results=$('#search-results');$('.calendar-layout').hidden=filtered;results.hidden=!filtered;if(!filtered)return;const found=C.search(records,query,category),header=node('div','results-header');header.append(node('p','',`全部年份中找到 ${found.length} 条`),button('清除搜索',()=>{$('#search').value='';$('#category').value='all';renderSearch();}));results.replaceChildren(header);const g=node('div','search-grid');found.slice(searchPage*12,searchPage*12+12).forEach(r=>g.append(recordCard(r)));results.append(g);if(!found.length)results.append(node('p','empty','没有匹配的已收录记录。未收录的内容不在搜索范围内。'));if(found.length>12){const bar=node('div','pager'),prev=button('上一组',()=>{searchPage--;renderSearch();}),next=button('下一组',()=>{searchPage++;renderSearch();});prev.disabled=searchPage===0;next.disabled=(searchPage+1)*12>=found.length;bar.append(prev,node('span','',`${searchPage+1} / ${Math.ceil(found.length/12)}`),next);results.append(bar);}}
  $('#search').oninput=()=>{searchPage=0;renderSearch();};
  const categories=[...new Set(records.map(r=>r.category).filter(Boolean))];if(['taobao','jd'].includes(D.meta.platform)&&categories.length>1){$('#category-label').hidden=false;categories.sort().forEach(c=>$('#category').append(option(c,c)));}$('#category').onchange=()=>{searchPage=0;renderSearch();};
  $('#plan-month').append(option('unscheduled','暂不排期'));for(let m=1;m<=12;m++)$('#plan-month').append(option(m,m+'月'));$('#plan-month').onchange=renderPlans;
  function persistPlans(){save(keyPlans,plans);renderPlans();if(D.skin==='collage')renderReview();}
  function renderPlans(){
    const list=$('#plan-list');list.replaceChildren();const filter=$('#plan-month').value;
    plans.filter(p=>filter==='all'||(filter==='unscheduled'?!p.month:Number(p.month.slice(-2))===Number(filter)))
      .sort((a,b)=>(a.month||'9999').localeCompare(b.month||'9999')).forEach(p=>{
        const card=node('article','plan-card');card.dataset.done=!!p.done;
        card.append(node('span','plan-label',p.origin==='manual'?'自己写的小事':'根据记录整理的建议'),node('p','plan-date',p.month?p.month.replace('-','年')+'月':'有空再做 · 暂不排期'),node('h3','',p.title));
        if(p.reason)card.append(node('p','plan-reason',p.reason));if(p.note)card.append(node('p','',p.note));card.append(sources(p.source_ids));
        const actions=node('div','plan-actions');actions.append(button(p.done?'改为未完成':'标记完成',()=>{p.done=!p.done;persistPlans();}),button('编辑',()=>editPlan(p)),button('删除',()=>{const box=node('div');box.append(node('p','',`删除“${p.title}”？删除前会保存一份可恢复的本地备份。`),button('确认删除',()=>{if(!save(keyBackup,plans)){notify('备份未保存，已停止删除，请先下载备份。');return;}plans=plans.filter(x=>x.id!==p.id);persistPlans();$('#modal').close();}));showModal('删除计划',box);}));card.append(actions);list.append(card);
      });
    if(!list.children.length)list.append(node('p','empty',filter==='all'?'建议已被清空。可恢复备份，或新建一条计划。':'这里还没有计划，可新建或调整已有建议。'));
    $('#storage-note').textContent=storageAvailable?'修改保存在当前浏览器。换电脑、换浏览器或清理记录前，请下载 JSON 备份。':'当前浏览器不允许可靠保存。请及时下载 JSON 备份；刷新可能丢失修改。';
  }
  function editPlan(p){const form=node('form','plan-form');function field(text,tag,type,value){const l=node('label','',text),input=node(tag);if(type)input.type=type;input.value=value||'';l.append(input);form.append(l);return input;}const title=field('要做什么','input','text',p?.title),month=field('放在哪个月（可留空）','input','month',p?.month||''),note=field('给自己留句话（可空）','textarea',null,p?.note);title.required=true;title.maxLength=100;const actions=node('div','form-actions');actions.append(button('取消',()=>$('#modal').close()));const submit=node('button','primary','保存');submit.type='submit';actions.append(submit);form.append(actions);form.onsubmit=e=>{e.preventDefault();const updated={...(p||{id:'manual-'+Date.now()+'-'+Math.random().toString(36).slice(2,8),done:false,source_ids:[]}),title:title.value.trim(),month:month.value,note:note.value,origin:'manual'};if(!updated.title||!C.validPlans([updated]))return;if(p)plans=plans.map(x=>x.id===p.id?updated:x);else plans.push(updated);persistPlans();$('#modal').close();};showModal(p?'编辑计划':'新建计划',form);}
  $('#add-plan').onclick=()=>editPlan();
  function download(name,blob){const url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}
  $('#export-plans').onclick=()=>download('手账计划备份.json',new Blob([JSON.stringify({schema_version:2,project_key:D.project_key,plans},null,2)],{type:'application/json'}));
  $('#import-plans').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>2000000)throw new Error('文件过大');const raw=JSON.parse(await file.text()),incoming=Array.isArray(raw)?raw:raw.plans;if(!C.validPlans(incoming))throw new Error('计划数据格式不符合要求');if(raw.project_key&&raw.project_key!==D.project_key)throw new Error('这是另一个手账的计划，请先核对，不能直接混入');const box=node('div');box.append(node('p','',`读取到 ${incoming.length} 条。相同ID保留当前版本，新ID追加；将保存合并前备份。`),button('确认合并',()=>{if(!save(keyBackup,plans)){notify('备份未保存，已停止合并，请先下载备份。');return;}plans=C.mergePlans(plans,incoming);persistPlans();$('#modal').close();notify('已合并，相同ID的手动修改已保留。');}));showModal('合并计划',box);}catch(err){notify('未导入：'+err.message);}e.target.value='';};
  $('#restore-plans').onclick=()=>{const old=read(keyBackup,null);if(!C.validPlans(old)){notify('没有可恢复的有效备份。');return;}const box=node('div');box.append(node('p','',`恢复到备份中的 ${old.length} 条？当前版本也会保留，可再次切换。`),button('确认恢复',()=>{const current=plans;if(!save(keyBackup,current))return;plans=old;persistPlans();$('#modal').close();}));showModal('恢复计划',box);};
  function wrapText(ctx,text,x,y,width,line,maxLines=10){let row='',rows=0;for(const ch of text){if(ch==='\n'||ctx.measureText(row+ch).width>width){ctx.fillText(row,x,y);y+=line;row=ch==='\n'?'':ch;if(++rows>=maxLines){return y;}}else row+=ch;}if(row){ctx.fillText(row,x,y);y+=line;}return y;}
  async function exportTextShare(){const box=node('div');box.append(node('p','','默认不导出私人照片、账号、订单号或金额，只导出同一份回顾、节点与实际范围。'));const b=button('生成并下载 PNG',async()=>{try{
    const canvas=document.createElement('canvas');canvas.width=1080;canvas.height=1440;const c=canvas.getContext('2d'),accent=D.skin==='collage'?'#77618e':D.skin==='frosted'?'#edf633':'#da4945',soft=D.skin==='collage'?'#ded2eb':D.skin==='frosted'?'#eaf1bf':'#f5dfb8';
    c.fillStyle=D.skin==='collage'?'#f6f0e4':D.skin==='frosted'?'#dce2d5':'#f5f0e4';c.fillRect(0,0,1080,1440);
    function panel(x,y,w,h,fill){c.fillStyle=fill;c.beginPath();c.roundRect(x,y,w,h,22);c.fill();}
    panel(54,54,972,1332,'#ffffff90');panel(80,82,52,16,accent);c.fillStyle='#34312f';c.font='600 24px sans-serif';c.fillText(D.meta.title.slice(0,32),152,105);
    const headline=D.story.overview.headline||D.meta.title;c.font=`800 ${Math.min(66,Math.max(38,Math.floor(1550/headline.length)))}px sans-serif`;wrapText(c,headline,86,215,900,78,2);
    panel(80,350,920,350,soft);c.fillStyle='#34312f';c.font='27px sans-serif';wrapText(c,D.story.overview.text,110,405,860,43,7);
    c.font='600 18px sans-serif';c.fillStyle='#756f68';c.fillText('从记录里翻出的几个片段',86,744);
    const nodes=(D.story.milestones||D.story.themes).slice(0,3);nodes.forEach((m,i)=>{const y=770+i*122,r=byId.get(m.source_ids?.[0]);panel(80,y,920,108,i%2?'#f4f1e9':'#f1f0f5');c.fillStyle='#746481';c.font='700 23px sans-serif';c.fillText(r?.date.slice(0,7)||'',104,y+36);c.fillStyle='#34312f';c.font='650 28px sans-serif';wrapText(c,m.title,278,y+36,690,35,2);c.font='20px sans-serif';c.fillStyle='#756f68';wrapText(c,m.text||'可在完整手账中回查来源',278,y+77,690,27,1);});
    const foot=D.story.song?`推荐歌曲：${D.story.song.name} · ${D.story.song.artist}`:(D.story.findings?.[0]?D.story.findings[0].title+'：'+D.story.findings[0].text:'这些片段来自已收录的原始记录，未覆盖的部分不作推断。');panel(80,1162,920,98,soft);c.fillStyle='#34312f';c.font='22px sans-serif';wrapText(c,foot,106,1202,868,32,2);
    c.fillStyle='#756f68';c.font='18px sans-serif';wrapText(c,D.scope,86,1318,900,28,2);c.fillStyle=accent;c.fillRect(80,1361,920,5);
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!blob)throw new Error('浏览器未生成文件');download('手账回看_1080x1440.png',blob);notify('PNG 已生成，请检查下载文件。');$('#modal').close();
  }catch(err){notify('导出失败：'+err.message);}},'primary');box.append(b);showModal('导出一张可分享的回看',box);}
  async function exportShare(){
    if(D.skin!=='collage')return exportTextShare();
    if(window.JournalEditorialShare){
      const box=node('div'),status=node('p','share-status','正在排版这张物件刊页…');box.append(status);showModal('留一张回看',box);
      try{const canvas=await window.JournalEditorialShare.createCanvas(D);status.textContent='图片与文字来自这份手账，可保存为一张长图。';const actions=node('div','form-actions');actions.append(button('下载分享图 PNG',async()=>{const blob=await new Promise(r=>canvas.toBlob(r,'image/png'));if(blob)download('消费手账_1080x1440.png',blob);else notify('图片生成失败，请重试。');},'primary'));box.append(canvas,actions);}catch(e){status.textContent='分享图暂未生成：'+e.message;}return;
    }
    const box=node('div'),status=node('p','share-status','正在排版商品拼贴…');box.append(status);showModal('分享这一页',box);
    try{
      await document.fonts.ready;
      const canvas=document.createElement('canvas');canvas.width=1080;canvas.height=1440;canvas.className='share-preview';canvas.setAttribute('aria-label','包含真实商品图片的分享图预览');
      const c=canvas.getContext('2d'),ink='#2d2432',muted='#8b7892';
      function paper(x,y,w,h,fill,angle,draw){c.save();c.translate(x+w/2,y+h/2);c.rotate(angle*Math.PI/180);c.shadowColor='#35223d22';c.shadowBlur=20;c.shadowOffsetY=9;c.fillStyle=fill;c.beginPath();c.roundRect(-w/2,-h/2,w,h,8);c.fill();c.shadowColor='transparent';c.translate(-w/2,-h/2);draw?.();c.restore();}
      c.fillStyle='#f6f0e6';c.fillRect(0,0,1080,1440);c.strokeStyle='#a290741f';c.lineWidth=1;for(let x=0;x<=1080;x+=30){c.beginPath();c.moveTo(x,0);c.lineTo(x,1440);c.stroke();}for(let y=0;y<=1440;y+=30){c.beginPath();c.moveTo(0,y);c.lineTo(1080,y);c.stroke();}
      c.fillStyle=muted;c.font='600 22px ScrapBody,sans-serif';c.fillText(D.meta.title.slice(0,28),62,64);c.font='16px ScrapBody,sans-serif';c.fillText(`${D.meta.actual_range.start} — ${D.meta.actual_range.end}`,62,96);
      const title=D.story.overview.headline||D.meta.title;c.fillStyle=ink;c.font=`400 ${Math.min(145,Math.max(70,Math.floor(880/Math.min(title.length,10))))}px ScrapDisplay,sans-serif`;wrapText(c,title,57,228,960,140,2);
      const loaded=[];for(const asset of (D.share_images||[]).slice(0,4)){if(!/^data:image\/(png|jpeg|webp|gif|avif);base64,/.test(asset.data_url||''))continue;try{const img=await new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src=asset.data_url;});loaded.push({asset,img});}catch(e){/* Keep remaining genuine images, never substitute an invented product. */}}
      const positions=[[325,370,420,545,-3],[55,700,305,340,-8],[705,700,300,350,8],[785,365,220,300,9]];
      loaded.forEach(({asset,img},i)=>{
        const [x,y,w,h,angle]=positions[i];c.save();c.translate(x+w/2,y+h/2);c.rotate(angle*Math.PI/180);c.translate(-w/2,-h/2);
        if(asset.kind==='photo'||asset.kind==='design'||asset.kind==='cover'){c.shadowColor='#46324725';c.shadowBlur=16;c.shadowOffsetY=8;c.fillStyle=asset.kind==='cover'?'#45394f':'#fffdf9';c.fillRect(-9,-9,w+18,h+42);c.shadowColor='transparent';}
        const scale=Math.min(w/img.naturalWidth,(h-28)/img.naturalHeight),iw=img.naturalWidth*scale,ih=img.naturalHeight*scale;c.drawImage(img,(w-iw)/2,(h-28-ih)/2,iw,ih);
        c.restore();
      });
      // Paint labels after all images, so a later photograph cannot cover a product name.
      loaded.forEach(({asset},i)=>{const [x,y,w,h,angle]=positions[i];c.save();c.translate(x+w/2,y+h/2);c.rotate(angle*Math.PI/180);c.translate(-w/2,-h/2);c.fillStyle='#fffdf5ed';c.fillRect(4,h-9,w-8,36);c.fillStyle=muted;c.font='21px ScrapNote,sans-serif';wrapText(c,asset.caption,12,h+15,w-24,27,1);c.restore();});
      paper(55,370,270,232,'#fffdf9',-6,()=>{c.fillStyle='#d4a079b0';c.fillRect(78,-12,100,27);c.fillStyle=ink;c.font='25px ScrapNote,sans-serif';c.fillText('翻翻才发现',22,43);c.font='19px ScrapBody,sans-serif';wrapText(c,D.story.overview.note||D.story.overview.text,22,80,225,32,4);});
      if(!loaded.length){paper(360,450,625,420,'#ddd0ed',5,()=>{c.fillStyle=ink;c.font='36px ScrapNote,sans-serif';wrapText(c,D.story.themes[0]?.title||'从这些记录，翻回日子',35,80,555,56,3);c.font='23px ScrapBody,sans-serif';wrapText(c,D.story.themes[0]?.text||D.story.overview.text,35,250,555,38,4);});}
      const facts=(D.story.findings||[]).slice(0,2);paper(63,1110,950,190,'#eee59c',-1,()=>{facts.forEach((f,i)=>{const x=27+i*470;c.fillStyle=ink;c.font='27px ScrapNote,sans-serif';wrapText(c,f.title,x,48,423,34,1);c.fillStyle='#79694f';c.font='19px ScrapBody,sans-serif';wrapText(c,f.text,x,91,423,30,2);});});
      // Small original vector decorations, not factual images.
      c.save();c.translate(975,245);c.rotate(.2);c.fillStyle='#d6bee9';for(let i=0;i<4;i++){c.save();c.rotate(i*Math.PI/2);c.beginPath();c.ellipse(0,-26,17,30,0,0,Math.PI*2);c.fill();c.restore();}c.fillStyle='#e8d76f';c.beginPath();c.arc(0,0,15,0,Math.PI*2);c.fill();c.restore();
      c.fillStyle=ink;c.font='28px ScrapNote,sans-serif';c.fillText('下一页，还没下单。',68,1357);c.fillStyle=muted;c.font='16px ScrapBody,sans-serif';c.fillText(`${records.length} 笔已收录记录 · 图片对应原始商品`,68,1394);
      status.textContent=loaded.length?'商品拼贴预览，可直接下载。':'没有可用主视觉图片，保留有来源的文字，不补画商品。';
      const actions=node('div','form-actions');actions.append(button('下载分享图 PNG',async()=>{try{const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!blob)throw new Error('浏览器未生成图片');download('消费回看_1080x1440.png',blob);notify('分享图已生成。');}catch(e){notify('导出失败：'+e.message);}},'primary'));
      box.append(canvas,actions);
    }catch(e){status.textContent='分享图暂未生成：'+e.message;}
  }
  $('#share-button').onclick=exportShare;
  document.body.dataset.skin=D.skin;document.title=D.meta.title;$('#brand-title').textContent=D.meta.title;$('#scope').textContent=D.scope;$('#plan-heading').textContent=`${D.meta.plan_year}，留给接下来的小事`;
  const coverage=$('#coverage');D.coverage.forEach(c=>coverage.append(node('p','',`${c.year} · ${c.status} · ${c.note||''}`)));if(D.meta.coverage_note)coverage.prepend(node('p','',D.meta.coverage_note));
  renderReview();renderPlans();switchView(location.hash.slice(1));
  window.addEventListener('load',()=>window.scrollTo({top:0,behavior:'instant'}),{once:true});
})();
