/* Paper keepsake: source-bound photos, a compact flip-through dossier. */
(()=>{
 'use strict';let observer;let activeStage=0;
 const num=n=>String(n).padStart(2,'0');
 function pics(c,s,n=4){return c.assets(s).filter(a=>['object','photo','cover','design'].includes(a.kind)).slice(0,n);}
 function range(c,s){const ds=(s.source_ids||[]).map(id=>c.byId.get(id)?.date).filter(Boolean).sort();return s.period_label||s.range||(ds.length?ds[0].slice(0,4)+' — '+ds.at(-1).slice(0,4):'已收录记录');}
 function art(c,a,cls=''){const f=c.photo(a);f.className='pj-photo '+cls;f.dataset.kind=a.kind||'source';return f;}
 function evidence(c,s){const d=c.node('details','pj-evidence');d.append(c.node('summary','','翻看这几笔订单'),c.sources(s.source_ids));return d;}
 function link(c,text,id){const a=c.node('a','pj-primary',text);a.href='#'+id;return a;}
 function heading(c,no,title,note){const h=c.node('header','pj-heading');h.append(c.node('span','pj-number',no),c.node('h2','',title));if(note)h.append(c.node('p','pj-hand',note));return h;}
 function home(c){
  const {node,D,p,host,button}=c,hero=node('section','pj-hero'),copy=node('div','pj-hero-copy');
  const date=node('p','pj-edition');date.append(node('span','','PRIVATE COLLECTION'),node('strong','',D.meta.actual_range.start.slice(0,4)+'—'+D.meta.actual_range.end.slice(0,4)));copy.append(date);
  copy.append(node('h1','pj-title',p.headline||D.meta.title),node('p','pj-intro',p.text));
  const actions=node('div','pj-actions');actions.append(link(c,'拆开这些日子 ↘',D.story.stages?.length?'pj-stages':'pj-objects'),button('找一笔旧订单',()=>c.view('calendar'),'pj-text-button'));copy.append(actions);
  const gallery=node('div','pj-collage'),ims=pics(c,p,3);gallery.setAttribute('aria-label','几件收录的物品');
  ims.forEach((im,i)=>gallery.append(art(c,im,'pj-cover-'+i)));gallery.dataset.count=ims.length;gallery.append(node('span','pj-date-sticker','从购物车里\n翻出来的日常'));
  if(p.note)gallery.append(node('p','pj-yellow-note pj-hand',p.note));if(!ims.length)gallery.append(node('p','pj-text-cover',p.note||p.text));
  hero.append(copy,gallery);host.append(hero);
  const discoveries=node('div','pj-discoveries');(D.story.findings||[]).slice(0,3).forEach((f,i)=>{const d=node('article');d.append(node('span','pj-small-index',num(i+1)),node('h3','',f.title),node('p','',f.text));discoveries.append(d);});if(discoveries.childElementCount)host.append(discoveries);
  stages(c);objects(c);threads(c);closing(c);
 }
 function stages(c){
  const {node,D,host,button}=c,ss=D.story.stages||[];if(!ss.length)return;
  activeStage=Math.min(activeStage,ss.length-1);const section=node('section','pj-stages');section.id='pj-stages';section.append(heading(c,'01','把日子分几叠','每叠都有一点变化'));
  const folder=node('div','pj-folder'),tabs=node('div','pj-folder-tabs'),body=node('div','pj-folder-body'),panel=node('article','pj-folder-sheet');
  tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','翻阅生活阶段');panel.id='pj-stage-panel';panel.setAttribute('role','tabpanel');panel.tabIndex=0;
  const buttons=ss.map((s,i)=>{const b=button('',()=>select(i,true),'pj-folder-tab');b.append(node('span','',range(c,s)),node('strong','',s.label||s.title));b.id='pj-tab-'+i;b.setAttribute('role','tab');b.setAttribute('aria-controls',panel.id);b.addEventListener('keydown',e=>{if(['ArrowRight','ArrowLeft','Home','End'].includes(e.key)){e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?ss.length-1:(i+(e.key==='ArrowRight'?1:-1)+ss.length)%ss.length;select(next,true);buttons[next].focus();}});tabs.append(b);return b;});
  const controls=node('div','pj-folder-controls'),count=node('span','pj-folder-count'),prev=button('← 上一叠',()=>select(activeStage-1,true),'pj-flip'),next=button('下一叠 →',()=>select(activeStage+1,true),'pj-flip');controls.append(prev,count,next);
  function select(i,animate){activeStage=(i+ss.length)%ss.length;const s=ss[activeStage];buttons.forEach((b,j)=>{b.setAttribute('aria-selected',String(j===activeStage));b.tabIndex=j===activeStage?0:-1;});folder.dataset.tone=activeStage%3;panel.setAttribute('aria-labelledby',buttons[activeStage].id);panel.replaceChildren();
   const copy=node('div','pj-folder-copy');copy.append(node('span','pj-stamp','NO. '+num(activeStage+1)+' / '+range(c,s)));const h=node('h3','pj-stage-title');if(s.title_lines?.length)s.title_lines.forEach(t=>h.append(node('span','',t)));else h.textContent=s.title;copy.append(h,node('p','pj-stage-text',s.text),evidence(c,s));
   const ti=D.story.themes.findIndex(t=>t.id===s.detail_theme_id);if(ti>=0)copy.append(button('展开其中一件小事 ↗',()=>c.go(ti+1),'pj-text-button'));
   const gallery=node('div','pj-stage-gallery');pics(c,s,2).forEach((im,j)=>gallery.append(art(c,im,'pj-stage-photo-'+j)));if(s.notes?.[0]){const note=node('aside','pj-stage-note');note.append(node('span','pj-note-label',s.notes[0].title||'随手记'),node('p','pj-hand',s.notes[0].text));gallery.append(note);}if(!gallery.childElementCount)gallery.append(node('p','pj-text-cover',s.label||s.title));
   panel.append(copy,gallery);count.textContent=num(activeStage+1)+' / '+num(ss.length);prev.disabled=ss.length<2;next.disabled=ss.length<2;
   if(animate&&!matchMedia('(prefers-reduced-motion: reduce)').matches)panel.animate([{opacity:.25,transform:'translateY(14px) rotateX(-3deg)'},{opacity:1,transform:'translateY(0) rotateX(0)'}],{duration:420,easing:'cubic-bezier(.2,.8,.2,1)'});
  }
  body.append(panel,controls);folder.append(tabs,body);section.append(folder);host.append(section);select(activeStage,false);
 }
 function objects(c){const {node,D,host,button}=c;const seen=new Set();const themes=D.story.themes.map((t,i)=>({t,i})).filter(({t})=>{if(t.home===false||seen.has(t.claim_key||t.id))return false;seen.add(t.claim_key||t.id);return true;}).slice(0,4);if(!themes.length)return;
  const section=node('section','pj-objects');section.id='pj-objects';section.append(heading(c,'02','单独留一页','有些东西，值得再看一眼'));const grid=node('div','pj-object-grid');grid.dataset.count=themes.length;
  themes.forEach(({t,i},j)=>{const card=node('article','pj-object-card'),im=pics(c,t,1)[0];if(im)card.append(art(c,im));const copy=node('div','pj-object-copy');copy.append(node('span','pj-note-label','物件小记 / '+num(j+1)),node('h3','',t.title),node('p','',t.teaser||t.text),button('打开这页 ↗',()=>c.go(i+1),'pj-text-button'));card.append(copy);grid.append(card);});section.append(grid);host.append(section);}
 function threads(c){const {node,D,host}=c;if(!D.story.threads?.length)return;const section=node('section','pj-threads');section.append(heading(c,'03','隔了几年，又碰见','不只看买了什么，也看一直喜欢什么'));D.story.threads.forEach(t=>{const row=node('article','pj-thread'),copy=node('div','pj-thread-copy');copy.append(node('span','pj-note-label','一条藏在订单里的线索'),node('h3','',t.title),node('p','',t.text),evidence(c,t));const images=node('div','pj-thread-photos');pics(c,t,2).forEach(a=>images.append(art(c,a)));row.append(images,copy);section.append(row);});host.append(section);}
 function closing(c){const {node,D,host,button}=c,s=node('section','pj-coda'),copy=node('div');copy.append(node('p','pj-note-label','下一页，慢慢写'),node('h2','','喜欢的东西，\n别只留在订单里。'));if(D.story.closing)copy.append(node('p','',D.story.closing));copy.append(button('去看接下来的小事 ↗',()=>c.view('plans'),'pj-primary'));const list=node('div','pj-checklist');(c.plans||D.story.plans||[]).filter(p=>!p.done).slice(0,3).forEach(p=>{const r=node('div');r.append(node('span','pj-checkbox',''),node('p','',p.title));list.append(r);});if(!list.childElementCount)list.append(node('p','','暂时都安排好了。也可以写下新的小事。'));s.append(copy,list);host.append(s);const footer=node('footer','pj-footer');footer.append(node('p','pj-hand','就先翻到这里。'));const song=c.song();if(song)footer.append(song);host.append(footer);}
 function theme(c){const {node,p,host,D,page,button}=c,toolbar=node('div','pj-theme-toolbar');toolbar.append(button('← 放回回看首页',()=>c.go(0),'pj-text-button'),node('span','pj-note-label','物件小记 / '+num(page)));host.append(toolbar);const section=node('article','pj-detail');section.dataset.layout=p.layout||'A';const copy=node('div','pj-detail-copy');copy.append(node('span','pj-stamp',range(c,p)),node('h1','',p.title),node('p','pj-detail-text',p.text));if(p.note)copy.append(node('p','pj-hand',p.note));
  if(p.layout==='C'){const tl=node('ol','pj-timeline');(p.source_ids||[]).slice().sort((a,b)=>(c.byId.get(a)?.date||'').localeCompare(c.byId.get(b)?.date||'')).forEach(id=>{const r=c.byId.get(id);if(!r)return;const li=node('li');li.append(node('time','',r.date),node('span','',p.source_labels?.[id]||r.title));tl.append(li);});copy.append(tl);}copy.append(evidence(c,p));const images=node('div','pj-detail-photos');pics(c,p,p.layout==='B'?2:1).forEach(a=>images.append(art(c,a)));if(images.childElementCount)section.append(images);else section.classList.add('pj-text-only');section.append(copy);host.append(section);const more=node('div','pj-more');D.story.themes.forEach((t,i)=>{if(i+1!==page)more.append(button(t.title+' ↗',()=>c.go(i+1),'pj-text-button'));});host.append(more);}
 function render(c){if(observer)observer.disconnect();c.host.classList.add('playful-runtime');document.body.dataset.journalFramework='paper-keepsake-preview-v2';c.page===0?home(c):theme(c);if('IntersectionObserver'in window&&!matchMedia('(prefers-reduced-motion: reduce)').matches){observer=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('pj-entered');observer.unobserve(e.target);}}),{threshold:.06});c.host.querySelectorAll('.pj-object-card,.pj-thread,.pj-coda').forEach(el=>observer.observe(el));}}
 window.JournalScrapbook={render};
})();
