/* Taobao fixed scrapbook frames. Content is data, not executable markup. */
(()=>{
  'use strict';
  let observer=null,sizeObserver=null,resizeHandler=null;
  const art={
    heart:'<svg viewBox="0 0 120 110" xmlns="http://www.w3.org/2000/svg"><defs><radialGradient id="heart-pink" cx=".36" cy=".18" r=".85"><stop stop-color="#ffbad1"/><stop offset=".45" stop-color="#f873a1"/><stop offset=".78" stop-color="#d73f78"/><stop offset="1" stop-color="#91294f"/></radialGradient></defs><path d="M60 98C47 89 9 60 10 35C11 9 44 3 60 25C78 3 111 11 110 37C109 61 76 89 60 98Z" fill="url(#heart-pink)" stroke="#fffdf7" stroke-width="9"/><path d="M25 35C26 19 43 17 48 26" fill="none" stroke="#fff9" stroke-width="6" stroke-linecap="round"/></svg>',
    star:'<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg"><path d="M50 6L60 36L91 29L71 54L90 81L59 72L49 99L39 70L9 80L27 55L6 30L39 37Z" fill="#e9d76d" stroke="#fffdf7" stroke-width="7" stroke-linejoin="round"/><path d="M43 51q7 8 14 0" fill="none" stroke="#51404f" stroke-width="2.5" stroke-linecap="round"/></svg>',
    arrow:'<svg viewBox="0 0 130 70" xmlns="http://www.w3.org/2000/svg"><path d="M7 18C41 66 82 55 113 18M96 17L117 14L114 35" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    flower:'<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg"><g fill="#c8b4e6" stroke="#fffdf7" stroke-width="4"><ellipse cx="50" cy="25" rx="15" ry="23"/><ellipse cx="50" cy="75" rx="15" ry="23"/><ellipse cx="25" cy="50" rx="23" ry="15"/><ellipse cx="75" cy="50" rx="23" ry="15"/></g><circle cx="50" cy="50" r="15" fill="#f0dc73" stroke="#fffdf7" stroke-width="4"/></svg>'
  };
  function sticker(node,kind,cls){const el=node('span','scrap-sticker '+(cls||''));el.setAttribute('aria-hidden','true');el.innerHTML=art[kind];return el;}
  function photos(ctx,section,limit=5){return ctx.assets(section).slice(0,limit);}
  function showPhoto(ctx,asset,cls){
    const kind=asset.kind||'source',caption=asset.caption||'一笔购买记录',short=Array.from(caption).length>24?Array.from(caption).slice(0,20).join('')+'…':caption;
    const fig=ctx.photo({...asset,caption:short});fig.classList.remove('photo');fig.classList.add('scrap-photo','journal-artifact','media-'+kind);fig.dataset.mediaKind=kind;
    if(kind==='service'||kind==='source'){
      const open=fig.querySelector('button');open.replaceChildren(ctx.node('span','artifact-type',kind==='service'?'服务订单 · 记录卡':'订单摘要'),ctx.node('strong','artifact-title',short),ctx.node('span','artifact-date','下单于 '+asset.date),ctx.node('span','artifact-open','查看原图 ↗'));
      fig.querySelector('figcaption').hidden=true;
    }
    if(cls)fig.classList.add(cls);return fig;
  }
  function bodyText(ctx,section){const box=ctx.node('div','story-copy');box.append(ctx.node('p','',section.text));if(section.note)box.append(ctx.node('p','small-hand-note',section.note));return box;}
  function evidence(ctx,section){const detail=ctx.node('details','scrap-evidence'),summary=ctx.node('summary','','看看这些订单');detail.append(summary,ctx.sources(section.source_ids));return detail;}
  function range(ctx,section){const dates=(section.source_ids||[]).map(id=>ctx.byId.get(id)?.date).filter(Boolean).sort();return section.range||(dates.length?(dates[0]===dates.at(-1)?dates[0]:dates[0]+' — '+dates.at(-1)):'日期以原订单为准');}
  function headline(ctx,text,cls){const heading=ctx.node('h1',cls,text);heading.style.setProperty('--letters',String(Math.max(6,Array.from(text).length)));return heading;}
  function gallery(ctx,section,cls){const list=ctx.node('div','scrap-gallery '+(cls||'')),assets=photos(ctx,section);list.dataset.count=String(assets.length);if(!assets.length){list.classList.add('no-photos');list.append(ctx.node('p','source-note','这段记录用文字和订单来源呈现。'));return list;}assets.forEach((a,i)=>{const frame=showPhoto(ctx,a);frame.style.setProperty('--i',i);list.append(frame);});return list;}
  function homeThemes(D){const primary=new Set([...(D.story.stages||[]),...(D.story.threads||[])].map(x=>x.claim_key).filter(Boolean));return D.story.themes.filter(t=>t.home!==false&&(!t.claim_key||!primary.has(t.claim_key)));}
  function sectionHead(ctx,eyebrow,title){const box=ctx.node('header','life-section-head');box.append(ctx.node('p','hand-kicker',eyebrow),ctx.node('h2','display-heading',title));return box;}
  function objectShelf(ctx){
    const {node,D,button,host}=ctx,section=node('section','object-shelf');
    section.append(sectionHead(ctx,'几件东西，先把记忆叫回来。','这些东西，还记得吗？'));
    const grid=node('div','object-shelf-grid');
    const selected=homeThemes(D).slice(0,3);if(!selected.length)return;section.dataset.count=String(selected.length);
    selected.forEach((t,i)=>{
      const card=node('article','object-memory'),pictures=node('div','object-memory-photos');
      photos(ctx,t,2).forEach(a=>pictures.append(showPhoto(ctx,a)));
      const copy=node('div','object-memory-copy');copy.append(node('span','memory-index','0'+(i+1)),node('h3','',t.title),node('p','',t.teaser||t.text),button('翻看这件事 ↗',()=>ctx.go(D.story.themes.indexOf(t)+1),'text-link'));
      card.append(pictures,copy);grid.append(card);
    });section.id='objects';section.append(grid);host.append(section);
  }
  function lifeStages(ctx){
    const {node,D,host,button}=ctx,hasStages=!!D.story.stages?.length;
    if(!hasStages)return; // Missing evidence is not a reason to relabel themes as life stages.
    const chapters=D.story.stages;
    const section=node('section','life-chapters');section.id='life-chapters';
    section.append(sectionHead(ctx,hasStages?'按时间翻，买东西的重心也在变。':'沿着真实记录，翻几段具体的小事。',hasStages?'原来，日子换过几种过法。':'把这些小事，装进文件夹。'));
    const index=node('nav','stage-index');index.setAttribute('aria-label','阶段快速跳转');
    chapters.forEach((s,i)=>{const a=node('a','',s.label||s.title);a.href='#chapter-'+i;index.append(a);});section.append(index);
    const stack=node('div','life-folder-stack');
    chapters.forEach((s,i)=>{
      const panel=node('article','life-folder life-folder-'+i%4);panel.id='chapter-'+i;panel.dataset.arrangement=s.arrangement||['spread','ledger','contrast'][i%3];panel.style.setProperty('--chapter',i);
      const tab=node('div','life-folder-tab');tab.append(node('span','',String(i+1).padStart(2,'0')),node('span','',s.label||s.period_label||s.title));panel.append(tab);
      const inside=node('div','life-folder-inside'),main=node('div','life-folder-main'),side=node('aside','life-folder-side');
      const chapterTitle=node('h3','chapter-title');
      if(s.title_lines?.length)s.title_lines.forEach(line=>chapterTitle.append(node('span','chapter-title-line',line)));else chapterTitle.textContent=s.title;
      main.append(node('p','chapter-period',s.period_label||range(ctx,s)),chapterTitle,node('p','chapter-story',s.text));
      const artifacts=node('div','chapter-artifacts');
      photos(ctx,s,3).forEach((a,j)=>{const fig=showPhoto(ctx,a);fig.style.setProperty('--artifact',j);artifacts.append(fig);});
      if(artifacts.childElementCount)main.append(artifacts);
      const fact=node('div','chapter-fact-paper');fact.append(node('span','tape'),node('p','hand-heading','这段时间留下了…'));
      const facts=node('div','chapter-fact-list');
      const categories=[...new Set((s.source_ids||[]).map(id=>ctx.byId.get(id)?.category).filter(Boolean))];
      categories.slice(0,3).forEach(x=>facts.append(node('span','fact-sticker',x)));fact.append(facts);
      fact.append(node('p','chapter-dates',range(ctx,s)),evidence(ctx,s));side.append(fact);
      const notes=s.notes?.length?s.notes:(s.note?[{title:'留在这一页',text:s.note}]:[]);
      notes.slice(0,2).forEach(n=>{const note=node('div','chapter-side-note');note.append(node('span','paperclip'),node('h4','',n.title),node('p','',n.text));side.append(note);});
      if(s.detail_theme_id){const idx=D.story.themes.findIndex(t=>t.id===s.detail_theme_id);if(idx>=0)side.append(button('这一页里，还有件小事 ↗',()=>ctx.go(idx+1),'chapter-detail-link'));}
      inside.append(main,side);panel.append(inside);stack.append(panel);
    });section.append(stack);host.append(section);
  }
  function threads(ctx){
    const {node,D,host}=ctx,list=D.story.threads||[];
    if(!list.length)return;
    const section=node('section','life-threads');section.id='life-threads';section.append(sectionHead(ctx,'也有些东西，没跟着年份走远。','一直没变的，也挺有意思。'));
    list.forEach((t,i)=>{
      const row=node('article','life-thread'),copy=node('div','thread-copy'),strip=node('div','thread-strip');
      copy.append(node('span','hand-number','0'+(i+1)),node('h3','',t.title),node('p','',t.text),evidence(ctx,t));
      photos(ctx,t,3).forEach(a=>strip.append(showPhoto(ctx,a)));row.append(copy,strip);section.append(row);
    });host.append(section);
  }
  function closing(ctx){
    const {node,button,D,host}=ctx,section=node('section','life-coda');
    section.append(sectionHead(ctx,'翻到最后，不用急着下结论。','下一页，还没下单。'));
    const spread=node('div','coda-spread'),letter=node('div','coda-letter');spread.dataset.letter=String(!!D.story.closing);if(D.story.closing)letter.append(node('span','tape'),node('p','',D.story.closing));
    const actions=node('div','coda-actions');D.story.plans.slice(0,3).forEach((p,i)=>{const item=node('div','coda-action');item.append(node('span','',String(i+1).padStart(2,'0')),node('p','',p.title));actions.append(item);});actions.append(button('把接下来的小事排一排 →',()=>ctx.view('plans'),'sticker-button'));
    if(D.story.closing)spread.append(letter);spread.append(actions);section.append(spread);const music=ctx.song();if(music)section.append(music);host.append(section);
  }
  function home(ctx){
    const {node,button,p,D,host}=ctx,hero=node('section','scrap-hero');
    hero.append(node('div','scrap-kicker','CONSUMPTION JOURNAL / '+D.meta.actual_range.start.slice(0,4)+'—'+D.meta.actual_range.end.slice(0,4)));
    const title=node('div','scrap-title-wrap');title.append(headline(ctx,p.headline,'scrap-title'),sticker(node,'heart','hero-heart'));hero.append(title);
    const stage=node('div','scrap-stage'),left=node('div','hero-note reveal'),right=node('aside','hero-findings reveal');
    left.append(node('span','tape'),node('p','note-label','翻翻才发现'),node('p','hero-summary',p.text));if(p.note)left.append(node('p','hero-note-aside',p.note));left.append(evidence(ctx,p));
    const pictures=gallery(ctx,p,'hero-gallery');pictures.classList.add('reveal');
    right.append(node('span','paperclip'),node('div','pill-strip','这几笔，值得翻出来'),node('h2','hand-heading','购物车的小线索'));
    (D.story.findings||[]).slice(0,2).forEach((f,i)=>{const row=node('div','hero-finding');row.append(node('span','finding-number',String(i+1).padStart(2,'0')),node('strong','',f.title),node('p','',f.text));right.append(row);});
    stage.append(left,pictures,right,sticker(node,'flower','hero-flower'));hero.append(stage);host.append(hero);
    const anchors=node('nav','home-anchor-nav');anchors.setAttribute('aria-label','回看章节');[['objects','几件旧物',homeThemes(D).length],['life-chapters','几段日子',D.story.stages?.length],['life-threads','一直没变的',D.story.threads?.length]].forEach(([id,text,count])=>{if(!count)return;const a=node('a','',text+' ↘');a.href='#'+id;anchors.append(a);});host.append(anchors);
    objectShelf(ctx);lifeStages(ctx);threads(ctx);closing(ctx);
  }
  function theme(ctx){
    const {node,button,p,page,host}=ctx,layout=p.layout||'A',section=node('article','scrap-theme scrap-layout-'+layout);
    const toolbar=node('div','scrap-theme-toolbar');toolbar.append(button('← 回到拼贴首页',()=>ctx.go(0),'back-to-cover'),node('span','',String(page).padStart(2,'0')+' / '+String(ctx.D.story.themes.length).padStart(2,'0')));host.append(toolbar);
    const heading=node('div','scrap-theme-head');heading.append(node('span','scrap-tab-label','小故事 '+String(page).padStart(2,'0')),headline(ctx,p.title,'theme-title'),node('p','theme-range',range(ctx,p)));section.append(heading);
    const content=node('div','scrap-theme-content');
    if(layout==='B'){
      const cards=gallery(ctx,p,'comparison-gallery');content.append(cards,bodyText(ctx,p));
    }else if(layout==='C'){
      const receipt=node('div','story-receipt');receipt.append(node('p','receipt-heading','这些订单，连在一起看'));(p.source_ids||[]).slice().sort((a,b)=>(ctx.byId.get(a)?.date||'').localeCompare(ctx.byId.get(b)?.date||'')).slice(0,6).forEach(id=>{const r=ctx.byId.get(id);if(!r)return;const row=node('div','receipt-row');const short=p.source_labels?.[id]||r.category||r.title.slice(0,20);row.append(node('time','',r.date),node('span','',short));receipt.append(row);});receipt.append(node('p','receipt-end','· · · 下单记录，不是使用日期 · · ·'));content.append(receipt,gallery(ctx,p,'receipt-gallery'),bodyText(ctx,p));
    }else{
      content.append(gallery(ctx,p,'single-gallery'),bodyText(ctx,p));
    }
    content.append(sticker(node,layout==='B'?'heart':'star','theme-corner-sticker'));section.append(content,evidence(ctx,p));host.append(section);
    const related=node('aside','related-folders');related.append(node('p','hand-kicker','再翻一个？'));ctx.D.story.themes.forEach((t,i)=>{if(i+1!==page)related.append(button(t.title+' ↗',()=>ctx.go(i+1),'mini-folder-link'));});host.append(related);
  }
  function motion(ctx){
    if(observer)observer.disconnect();if(sizeObserver)sizeObserver.disconnect();if(resizeHandler)window.removeEventListener('resize',resizeHandler);
    const fitFolders=()=>ctx.host.querySelectorAll('.life-folder').forEach(el=>{const flow=el.getBoundingClientRect().height>window.innerHeight-115;if(el.dataset.flow!==String(flow))el.dataset.flow=String(flow);});
    resizeHandler=fitFolders;window.addEventListener('resize',resizeHandler);fitFolders();
    if('ResizeObserver' in window){sizeObserver=new ResizeObserver(fitFolders);ctx.host.querySelectorAll('.life-folder').forEach(el=>sizeObserver.observe(el));}
    const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
    // Above-the-fold paper must never stay invisible after a fast scroll away.
    ctx.host.querySelectorAll('.scrap-stage > .reveal').forEach(el=>el.classList.add('revealed'));
    if('IntersectionObserver' in window&&!reduce){observer=new IntersectionObserver(entries=>{entries.forEach(e=>{if(e.isIntersecting){e.target.classList.add('revealed');observer.unobserve(e.target);}});},{threshold:.12});ctx.host.querySelectorAll('.reveal:not(.revealed)').forEach(el=>observer.observe(el));}
    else ctx.host.querySelectorAll('.reveal').forEach(el=>el.classList.add('revealed'));
    const stage=ctx.host.querySelector('.scrap-stage');if(stage&&!reduce&&matchMedia('(pointer:fine)').matches){stage.addEventListener('pointermove',e=>{const box=stage.getBoundingClientRect();stage.style.setProperty('--mx',((e.clientX-box.left)/box.width-.5).toFixed(2));stage.style.setProperty('--my',((e.clientY-box.top)/box.height-.5).toFixed(2));});stage.addEventListener('pointerleave',()=>{stage.style.setProperty('--mx','0');stage.style.setProperty('--my','0');});}
  }
  function render(ctx){
    ctx.host.classList.add('scrapbook-runtime');ctx.page===0?home(ctx):theme(ctx);motion(ctx);
    const first=photos(ctx,ctx.D.story.overview,1)[0],preview=document.querySelector('#dock-preview');if(preview){if(first){preview.src=first.path;preview.hidden=false;}else preview.hidden=true;}
    document.body.dataset.journalFramework='editorial-media-v5';
  }
  window.JournalScrapbook={render};
})();
