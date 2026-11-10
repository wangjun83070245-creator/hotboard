(function(){
"use strict";
var D=JSON.parse(document.getElementById('data').textContent);
var S={};try{var se=document.getElementById('sum');S=JSON.parse(se.textContent)||{};if(typeof S!=="object"||Array.isArray(S))S={}}catch(e){S={}}
var CATS=D.tabs,WKEY="hotradar.watch.v2",TKEY="hotradar.theme",IT=D.items;
var notice="";
function readHash(){var h="";try{h=decodeURIComponent(location.hash.slice(1))}catch(e){h="?"}
 if(!h)return"全部";if(h==="★"||CATS.indexOf(h)>=0)return h;notice="没有这个分类，已显示全部";history.replaceState(null,"","#"+encodeURIComponent("全部"));return"全部"}
var cur=readHash();
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
function safeUrl(u){return /^https?:\/\//i.test(u||"")?u:"#"}
function p2(n){return(n<10?"0":"")+n}
function jst(iso,short){if(!iso)return"—";var d=new Date(iso);if(isNaN(d))return"—";var j=new Date(d.getTime()+9*3600e3);return(short?"":p2(j.getUTCMonth()+1)+"-"+p2(j.getUTCDate())+" ")+p2(j.getUTCHours())+":"+p2(j.getUTCMinutes())+(short?"":" JST")}
function load(){try{var w=JSON.parse(localStorage.getItem(WKEY)||"{}");return w&&typeof w==="object"?w:{}}catch(e){return{}}}
function save(w){try{localStorage.setItem(WKEY,JSON.stringify(w))}catch(e){}}
var W=load();
var th=null;try{th=localStorage.getItem(TKEY)}catch(e){}
if(th==="dark"||th==="light")document.documentElement.dataset.theme=th;
document.getElementById('theme').onclick=function(){var r=document.documentElement,dark=r.dataset.theme?r.dataset.theme==="dark":matchMedia('(prefers-color-scheme:dark)').matches;r.dataset.theme=dark?"light":"dark";try{localStorage.setItem(TKEY,r.dataset.theme)}catch(e){}};
function rowOf(id,c){var L=D.cats[c]||[];for(var i=0;i<L.length;i++)if(L[i].id===id)return L[i];return null}
function zh(x){var s=S[x.id];return s&&typeof s.title==="string"&&s.title.trim()?s:null}
function title(x){var s=zh(x);return s?s.title:x.title}
function summ(x){var s=zh(x);if(!s||typeof s.summary!=="string"||!s.summary.trim())return"";var t=Array.from(s.summary.trim());return t.length>50?t.slice(0,49).join("")+"…":t.join("")}
var missing=0;Object.keys(IT).forEach(function(k){if(!zh(IT[k]))missing++});
function delta(r){if(r.delta===null||r.delta===undefined)return'<span class="dl same" title="首次快照，无上一小时数据">首次</span>';
 if(r.delta==="new")return'<span class="dl new">NEW</span>';if(r.delta>0)return'<span class="dl up" title="较上次快照上升">▲'+r.delta+'</span>';
 if(r.delta<0)return'<span class="dl down" title="较上次快照下降">▼'+(-r.delta)+'</span>';return'<span class="dl same" title="持平">—</span>'}
function spark(r){var h=(r.hist||[]).map(function(p){return p.heat});var v=h.filter(function(a){return a!=null});if(!v.length)return"";
 var mx=Math.max.apply(null,v),mn=Math.min.apply(null,v),rg=mx-mn||1,n=h.length,pts=[];
 h.forEach(function(a,i){if(a==null)return;var X=n>1?4+i*(88/(n-1)):48,Y=24-(a-mn)/rg*20;pts.push(X.toFixed(1)+","+Y.toFixed(1))});
 var last=pts[pts.length-1].split(",");var lbl="热度 "+v.map(function(a){return a.toFixed(0)}).join("→");
 return'<svg class="sp" viewBox="0 0 96 28" role="img" aria-label="'+esc(lbl)+'"><title>'+esc(lbl)+'</title><line x1="0" y1="27" x2="96" y2="27" stroke="var(--line)"/>'+(pts.length>1?'<polyline fill="none" stroke="var(--spark)" stroke-width="2" points="'+pts.join(" ")+'"/>':'')+'<circle cx="'+last[0]+'" cy="'+last[1]+'" r="3" fill="var(--spark)"/></svg>'}
function srcs(x){var f=[],n=[];x.members.forEach(function(m){if(f.indexOf(m.family)<0){f.push(m.family);n.push(m.source)}});return n.slice(0,3).join(" · ")+(x.k>3?" 等"+x.k+"个源":"")}
function watchBtn(x,c){var on=!!W[x.id];return'<button class="btn" type="button" data-w="'+esc(x.id)+'" data-wc="'+esc(c)+'" aria-pressed="'+on+'">'+(on?"★ 已关注":"☆ 关注")+'</button>'}
function detBtn(x,c){return'<button class="btn" type="button" data-d="'+esc(x.id)+'" data-dc="'+esc(c)+'">详情</button>'}
function link(x){return'<a href="'+esc(safeUrl(x.url))+'" target="_blank" rel="noopener noreferrer">'+esc(title(x))+'</a>'}
function sumLine(x){var s=summ(x);return s?'<p class="sum">'+esc(s)+'</p>':""}
function tags(x){return x.cats.filter(function(c){return CATS.indexOf(c)>=0}).map(function(c){return'<span class="tag">'+esc(c)+'</span>'}).join("")}
function card(r){var x=IT[r.id];return'<li class="card r'+r.rank+'"><div><div class="rk">'+r.rank+'</div>'+delta(r)+'</div><div><h3 class="ttl">'+link(x)+'</h3>'+sumLine(x)+
 '<div class="meta"><span class="heat" title="综合热度（0–100）">🔥 '+x.H.toFixed(1)+'</span>'+spark(r)+'<span>'+esc(srcs(x))+'</span><span>首发 '+esc(jst(x.first_pub))+'</span>'+tags(x)+'</div></div><div class="ops">'+watchBtn(x,cur)+detBtn(x,cur)+'</div></li>'}
function row(r){var x=IT[r.id];return'<li><div><div class="rk">'+r.rank+'</div>'+delta(r)+'</div><div><h3 class="ttl">'+link(x)+'</h3><div class="meta"><span class="heat">🔥 '+x.H.toFixed(1)+'</span><span>'+esc(srcs(x))+'</span></div></div><div class="side">'+spark(r)+watchBtn(x,cur)+detBtn(x,cur)+'</div></li>'}
function tabs(){var h=CATS.map(function(c){var n=(D.cats[c]||[]).length;return'<button class="chip" role="tab" type="button" data-c="'+esc(c)+'" aria-selected="'+(c===cur)+'">'+esc(c)+'<i>'+n+'</i></button>'}).join("");
 h+='<span class="spacer"></span><button class="chip" role="tab" type="button" data-c="★" aria-selected="'+(cur==="★")+'">★ 关注<i>'+Object.keys(W).length+'</i></button>';document.getElementById('tabs').innerHTML=h}
function render(){var fk=null,a=document.activeElement;if(a&&a.tagName==="BUTTON"){fk=["c","w","d"].map(function(k){return a.dataset[k]!=null?'[data-'+k+'="'+CSS.escape(a.dataset[k])+'"]':""}).join("")}
 tabs();var m=document.getElementById('main'),h=notice?'<p class="warn" role="status">'+esc(notice)+'</p>':"";
 if(cur==="★"){var ks=Object.keys(W);if(!ks.length){m.innerHTML=h+'<div class="emp">还没有关注的条目。点任一条目的“☆ 关注”即可加入，保存在本机浏览器。</div>'}
  else m.innerHTML=h+'<h2>我的关注（'+ks.length+'）</h2><ol class="rest wl">'+ks.map(function(k){var w=W[k],c=w.cat||"全部",r=rowOf(k,c),x=IT[k];
   var st=r?'当前「'+esc(c)+'」#'+r.rank+' · 🔥 '+x.H.toFixed(1):'<span class="down">已掉出前 20</span> · 最后「'+esc(c)+'」#'+esc(w.lastRank)+'（'+esc(jst(w.lastAt))+'）';
   return'<li><div><h3 class="ttl"><a class="lk" href="'+esc(safeUrl(w.url))+'" target="_blank" rel="noopener noreferrer">'+esc(x?title(x):w.title)+'</a></h3><div class="meta">'+st+'</div></div><div class="side">'+(r?detBtn(x,c):"")+'<button class="btn" type="button" data-w="'+esc(k)+'" aria-pressed="true">移除</button></div></li>'}).join("")+'</ol>'}
 else{var L=D.cats[cur]||[];if(!L.length)m.innerHTML=h+'<div class="emp">本小时「'+esc(cur)+'」暂无上榜条目（可能对应数据源未返回）。其他分类不受影响。</div>';
  else{var A=L.slice(0,10),B=L.slice(10,20);m.innerHTML=h+'<h2>前 10 名</h2><ol class="top10">'+A.map(card).join("")+'</ol>'+(B.length?'<h2>第 11–'+(10+B.length)+' 名</h2><ol class="rest">'+B.map(row).join("")+'</ol>':"")}}
 if(fk){var e=document.querySelector('button'+fk);if(e)e.focus()}}
var net="";
function status(){var age=(Date.now()-new Date(D.at).getTime())/3600e3,bad=(D.sources||[]).filter(function(s){return!s.ok&&!s.skipped}),s="";
 if(net)s+='<p class="warn" role="status">'+esc(net)+'</p>';
 if(age>2)s+='<p class="warn" id="stale">数据已 '+age.toFixed(1)+' 小时未更新，可能是定时任务停了。</p>';
 if(bad.length)s+='<p class="warn" id="srcfail">本次 '+bad.length+' 个源未取到（该源本小时失败）：'+bad.map(function(b){return esc(b.name)}).join("、")+'。排名基于其余源。</p>';
 if(missing)s+='<p class="tiny">部分标题未翻译</p>';
 document.getElementById('status').innerHTML=s}
function upd(){var nx=new Date(new Date(D.at).getTime()+3600e3).toISOString();
 document.getElementById('upd').innerHTML='数据时间 <b>'+esc(jst(D.at))+'</b> · 对比 '+(D.prev_at?esc(jst(D.prev_at))+(D.gap_h>1?'（跨 '+D.gap_h+' 小时）':''):"无（首次快照）")+' · 下次约 '+esc(jst(nx));
 status();
 var _ghb=document.getElementById('gh-basis'),_ght=_ghb?_ghb.textContent:"";
 document.getElementById('foot').innerHTML='<p id="basis">排序依据：名次、互动数、跨源数，不含点击率</p><p>热度 = 100 ×（0.65×互动分 + 0.35×跨源分）× 0.5^(小时/8)。中文标题与摘要为人工维护，没有记录时显示原标题。</p>'+(_ght?'<p id="gh-basis">'+esc(_ght)+'</p>':"")}
var dlg=document.getElementById('dlg'),opener=null;
function detail(id,c,btn){var x=IT[id];if(!x)return;c=c&&c!=="★"?c:"全部";var r=rowOf(id,c)||rowOf(id,"全部");opener=btn||null;
 document.getElementById('dt').textContent=(r?'#'+r.rank+'（'+c+'） ':'')+title(x);
 var z=zh(x),h='<p class="meta"><span class="heat">🔥 '+x.H.toFixed(2)+'</span>'+tags(x)+'</p>';
 if(z)h+='<p class="orig">原题：'+esc(x.title)+'</p>'+(summ(x)?'<p>'+esc(summ(x))+'</p>':'');
 h+='<h3>热度怎么算</h3><p><code>100 × (0.65×E '+x.E+' + 0.35×D '+x.D+') × 衰减 '+x.decay+' = '+x.H.toFixed(2)+'</code></p><p class="note">E=互动分（各源按互动数名次百分位归一，乘来源权重，主源+次源×0.3，最多 3 个源，再 /1.6）；D=跨源分（'+x.k+' 个源，按源家族去重，log2(1+k)/log2(7)）；衰减按最早发布 '+esc(jst(x.first_pub))+'，距今 '+x.age_h+' 小时，半衰期 8 小时。</p>';
 h+='<h3>各源互动</h3><table><tr><th>来源</th><th>互动</th><th class="num">归一</th><th class="num">权重</th></tr>'+x.members.map(function(s){var m=Object.keys(s.metrics).map(function(k){return({points:"点",comments:"评",score:"分",upvotes:"赞",position:"名次 #",related:"相关报道 "}[k]||k)+s.metrics[k]}).join(" · ");
  return'<tr><td><a href="'+esc(safeUrl(s.url))+'" target="_blank" rel="noopener noreferrer">'+esc(s.source)+'</a>'+(s.disc?' <a href="'+esc(safeUrl(s.disc))+'" target="_blank" rel="noopener noreferrer">讨论</a>':"")+'</td><td>'+esc(m)+'</td><td class="num">'+s.norm.toFixed(2)+'</td><td class="num">'+s.weight+'</td></tr>'}).join("")+'</table>';
 h+='<h3>排名轨迹（'+esc(c)+'）</h3><table><tr><th>快照</th><th class="num">名次</th><th class="num">热度</th></tr>'+((r&&r.hist)||[]).map(function(p){return'<tr><td>'+esc(jst(p.at))+'</td><td class="num">'+(p.rank||"未上榜")+'</td><td class="num">'+(p.heat!=null?p.heat.toFixed(1):"—")+'</td></tr>'}).join("")+'</table>';
 h+='<p><a class="go" href="'+esc(safeUrl(x.url))+'" target="_blank" rel="noopener noreferrer">阅读原文 ↗</a></p>';
 document.getElementById('db').innerHTML=h;if(dlg.showModal)dlg.showModal();else dlg.setAttribute('open','');dlg.scrollTop=0}
dlg.addEventListener('close',function(){if(opener&&document.contains(opener))opener.focus();else{var e=opener&&document.querySelector('button[data-d="'+CSS.escape(opener.dataset.d)+'"]');if(e)e.focus()}});
document.getElementById('dx').onclick=function(){dlg.close()};
dlg.addEventListener('click',function(e){if(e.target===dlg)dlg.close()});
document.addEventListener('click',function(e){var t=e.target.closest('button');if(!t||t.id==="dx"||t.id==="theme")return;
 if(t.dataset.ghm&&t.dataset.ghfn){ghSetMark(t.dataset.ghfn,t.dataset.ghm);t.focus();ghRender();return}
 if(t.dataset.ghun){ghClearMark(t.dataset.ghun);t.focus();ghRender();return}
 if(t.dataset.ghl){ghList=ghList===t.dataset.ghl?"":t.dataset.ghl;t.focus();ghRender();return}
 if(t.dataset.ghb){ghBoard=t.dataset.ghb;ghList="";ghRender();return}
 if(t.dataset.ghc){ghCat=t.dataset.ghc;ghNotice="";ghList="";ghRender();return}
 if(t.dataset.c){cur=t.dataset.c;notice="";history.replaceState(null,"","#"+encodeURIComponent(cur));t.focus();render();return}
 if(t.dataset.d){detail(t.dataset.d,t.dataset.dc,t);return}
 if(t.dataset.w){var k=t.dataset.w;t.focus();if(W[k])delete W[k];else{var x=IT[k],c=t.dataset.wc||"全部",r=rowOf(k,c);W[k]={title:x.title,url:x.url,cat:c,addedAt:new Date().toISOString(),lastRank:r?r.rank:null,lastAt:D.at}}save(W);render()}});
window.addEventListener('hashchange',function(){cur=readHash();render()});
Object.keys(W).forEach(function(k){var r=rowOf(k,W[k].cat||"全部");if(r){W[k].lastRank=r.rank;W[k].lastAt=D.at}});save(W);
upd();render();
setInterval(status,60000);
// 断网自动重载：先 fetch latest.json，成功且有新数据才 reload；失败保留旧数据并显示横幅
function check(){if(document.hidden||dlg.open)return;
 if(navigator.onLine===false){net="网络断开，显示 "+jst(D.at,true)+" 的数据";status();return}
 fetch("latest.json?t="+Date.now(),{cache:"no-store"}).then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(j){net="";status();if(j&&j.at&&j.at!==D.at)location.reload()})
 .catch(function(){net="网络断开，显示 "+jst(D.at,true)+" 的数据";status()})}
window.__hbCheck=check;setInterval(check,600000);

var GH=null,GHS={};try{var ge=document.getElementById("gh");GH=JSON.parse(ge.textContent)||null;if(typeof GH!=="object"||Array.isArray(GH))GH=null}catch(e){GH=null}
try{var gs=document.getElementById("ghsum");GHS=JSON.parse(gs.textContent)||{};if(typeof GHS!=="object"||Array.isArray(GHS))GHS={}}catch(e){GHS={}}
var GH_BLOCK={terms:[],need_signal:[],patch_signals:[],patch_signal_patterns:[],allowlist:[],blocklist_repos:[],name_terms:[],topic_free_terms:[],description_patterns:[]};
try{var gb=document.getElementById("gh-block");if(gb&&gb.textContent){var bc=JSON.parse(gb.textContent);if(bc&&typeof bc==="object"&&!Array.isArray(bc)){["terms","need_signal","patch_signals","patch_signal_patterns","allowlist","blocklist_repos","name_terms","topic_free_terms","description_patterns"].forEach(function(k){GH_BLOCK[k]=Array.isArray(bc[k])?bc[k]:[]})}}}catch(e){GH_BLOCK={terms:[],need_signal:[],patch_signals:[],patch_signal_patterns:[],allowlist:[],blocklist_repos:[],name_terms:[],topic_free_terms:[],description_patterns:[]}}
function ghEscRe(s){return String(s).replace(/[.*+?^${}()|[\]\\]/g,"\\$&")}
function ghAsciiTerm(term){return /^[A-Za-z0-9][A-Za-z0-9\- ]*$/.test(String(term||""))}
function ghFieldHasTerm(text,term){if(!text||!term)return false;if(ghAsciiTerm(term)){var parts=String(term).trim().split(/\s+/).filter(Boolean);try{return new RegExp("(?<![A-Za-z0-9_])"+parts.map(ghEscRe).join("\\s+")+"(?![A-Za-z0-9_])","i").test(String(text))}catch(e){return false}}return String(text).toLowerCase().indexOf(String(term).toLowerCase())>=0}
function ghNeedSignal(term){var w=String(term||"").toLowerCase();return (GH_BLOCK.need_signal||[]).some(function(s){return String(s).toLowerCase()===w})}
function ghTopicFree(term,field){if(field!=="topics")return false;var w=String(term||"").toLowerCase();return (GH_BLOCK.topic_free_terms||[]).some(function(s){return String(s).toLowerCase()===w})}
function ghCompanion(text){var i,pats;for(i=0;i<(GH_BLOCK.patch_signals||[]).length;i++){if(ghFieldHasTerm(text,GH_BLOCK.patch_signals[i]))return true}pats=GH_BLOCK.patch_signal_patterns||[];for(i=0;i<pats.length;i++){try{if(new RegExp(pats[i],"i").test(text||""))return true}catch(e){}}return false}
function ghNormName(s){return String(s||"").replace(/[-_.]+/g," ")}
function ghInRepoList(fn,list){var k=String(fn||"").toLowerCase();return (list||[]).some(function(x){return String(x).toLowerCase()===k})}
function ghFieldBlocked(text,field){var terms=GH_BLOCK.terms||[],i,t,hit;for(i=0;i<terms.length;i++){t=terms[i];hit=ghFieldHasTerm(text,t);if(!hit&&field==="topics")hit=ghFieldHasTerm(ghNormName(text),ghNormName(t));if(!hit)continue;if(ghNeedSignal(t)&&!ghTopicFree(t,field)&&!ghCompanion(text))continue;return true}return false}
function ghRepoBlocked(r){if(!r)return false;var fn=r.full_name||"";if(ghInRepoList(fn,GH_BLOCK.blocklist_repos))return true;if(ghInRepoList(fn,GH_BLOCK.allowlist))return false;if(ghFieldBlocked(r.description||"","description"))return true;var pats=GH_BLOCK.description_patterns||[],i;for(i=0;i<pats.length;i++){try{if(new RegExp(pats[i],"i").test(r.description||""))return true}catch(e){}}var topics=r.topics||[];for(i=0;i<topics.length;i++){if(ghFieldBlocked(String(topics[i]),"topics"))return true}var hay=ghNormName(fn),nts=GH_BLOCK.name_terms||[];for(i=0;i<nts.length;i++){if(ghFieldHasTerm(hay,ghNormName(nts[i])))return true}return false}
function ghMarkFields(k,it){var snap=(it&&it.snap)||{},pub=ghCatalog()[k]||{};return{full_name:snap.full_name||pub.full_name||k,description:snap.description||pub.description||"",topics:snap.topics||pub.topics||[]}}

var ghBoard="rising",ghCat="全部",ghNotice="",ghList="";
// Shown cap on the page. Public JSON and snapshots keep page_public and snapshot_top rows per board (see config/github_tags.yaml).
var GH_SHOW=20;
var GH_BOARDS=[{id:"rising",label:"飙升"},{id:"hot",label:"热度"},{id:"all",label:"总榜"}];
var MK_KEY="hotboard.marks.v1";
var MK_LABELS={interested:"感兴趣",not_interested:"不感兴趣",seen:"看过了"};
var MK_ORDER=["interested","not_interested","seen"];
var MK_SAVE_MSG="标记未能保存（浏览器存储不可用或已满）。本次仍生效，关闭或刷新后不会保存。";
function mkEmpty(){return{v:1,items:{}}}
function mkLoad(){try{var raw=localStorage.getItem(MK_KEY);if(!raw)return mkEmpty();var m=JSON.parse(raw);if(!m||typeof m!=="object"||Array.isArray(m))return mkEmpty();var src=m.items;if(!src||typeof src!=="object"||Array.isArray(src))return mkEmpty();var items={};Object.keys(src).forEach(function(k){var it=src[k];if(!it||typeof it!=="object"||Array.isArray(it))return;if(!MK_LABELS[it.state])return;var snap=it.snap&&typeof it.snap==="object"&&!Array.isArray(it.snap)?it.snap:{};items[String(k).toLowerCase()]={state:it.state,at:typeof it.at==="string"?it.at:"",snap:snap}});return{v:1,items:items}}catch(e){return mkEmpty()}}
var MK_STORE=mkLoad(),mkPersistOk=true;
function mkDump(){var items={};Object.keys(MK_STORE.items).forEach(function(k){var it=MK_STORE.items[k];items[k]={state:it.state,at:it.at||"",snap:it.snap||{}}});return{v:1,items:items}}
function mkSave(){try{localStorage.setItem(MK_KEY,JSON.stringify(mkDump()));mkPersistOk=true}catch(e){mkPersistOk=false}}
function ghSafeUrl(u){if(!u)return"";try{var p=new URL(String(u).trim());if(p.protocol.toLowerCase()!=="https:")return"";if(p.hostname.toLowerCase()!=="github.com")return"";if(p.username||p.password)return"";return p.href}catch(e){return""}}
function h(tag,attrs,kids){var e=document.createElement(tag);if(attrs)Object.keys(attrs).forEach(function(k){var v=attrs[k];if(v==null||v===false)return;if(k==="cls")e.className=v;else if(k==="text")e.textContent=v;else if(k==="dataset")Object.keys(v).forEach(function(d){e.dataset[d]=v[d]});else e.setAttribute(k,v===true?"":String(v))});(kids||[]).forEach(function(c){if(c)e.appendChild(c)});return e}
function ghCatalog(){var map={},boards=(GH&&GH.boards)||{};["rising","hot","all"].forEach(function(b){(boards[b]||[]).forEach(function(r){if(r&&r.full_name){var k=String(r.full_name).toLowerCase();if(!map[k])map[k]=r}})});return map}
function ghZh(r){if(!r||!r.full_name)return"";var s=GHS[r.full_name];if(s&&typeof s.summary==="string"&&s.summary.trim())return s.summary.trim();return""}
function ghIntro(r,allowEn){if(r&&typeof r.list_intro==="string"&&r.list_intro.trim())return r.list_intro.trim();var z=ghZh(r);if(z)return z;if(allowEn&&r&&typeof r.description==="string"&&r.description.trim())return r.description.trim();return""}
function ghItem(fn){return MK_STORE.items[String(fn||"").toLowerCase()]||null}
function ghIsMarked(fn){var it=ghItem(fn);return !!(it&&MK_LABELS[it.state])}
function ghSnapFor(fn){var r=ghCatalog()[String(fn).toLowerCase()]||{full_name:fn};var url=ghSafeUrl(r.url);return{full_name:r.full_name||fn,url:url||"",summary:ghZh(r)||"",description:(r.description&&String(r.description))||"",stars:r.stars!=null?r.stars:null,language:r.language||"",topics:Array.isArray(r.topics)?r.topics.slice():[]}}
function ghSetMark(fn,kind){if(!fn||!MK_LABELS[kind])return;var key=String(fn).toLowerCase(),prev=MK_STORE.items[key]||{},pub=ghCatalog()[key],snap=pub?ghSnapFor(fn):(prev.snap||{full_name:fn,url:"",summary:"",description:"",stars:null,language:"",topics:[]});MK_STORE.items[key]={state:kind,at:new Date().toISOString(),snap:snap};mkSave()}
function ghClearMark(fn){if(!fn)return;delete MK_STORE.items[String(fn).toLowerCase()];mkSave()}
function ghUnmarked(rows){var out=[];(rows||[]).forEach(function(r){if(!r||!r.full_name||ghIsMarked(r.full_name))return;out.push(r)});return out}
function ghShown(rows,cat,limit){var list=ghUnmarked(rows);if(cat&&cat!=="全部")list=list.filter(function(r){return(r.tags||[]).indexOf(cat)>=0});return list.map(function(r,i){var x=Object.assign({},r);x.orig_rank=r.rank;x.rank=i+1;return x}).slice(0,limit||GH_SHOW)}
function ghDelta(r){if(!r||r.board==="all")return"";if(r.stars_delta==null)return"";var w=r.stars_window==="24h_snapshot"?"约24h":"上一日";return(r.stars_delta>=0?"+":"")+r.stars_delta+" · "+w}
function ghNameEl(name,url){var href=ghSafeUrl(url),text=name||"";if(href){var a=h("a",{href:href,target:"_blank",rel:"noopener noreferrer"});a.textContent=text;return a}var s=h("span");s.textContent=text;return s}
function ghMarkBtns(fn,pressed){var wrap=h("div",{cls:"ops gh-ops"});MK_ORDER.forEach(function(k){var b=h("button",{cls:"btn",type:"button",dataset:{ghm:k,ghfn:fn}});if(pressed===k)b.setAttribute("aria-pressed","true");b.textContent=MK_LABELS[k];wrap.appendChild(b)});return wrap}
function ghRankBox(r){var box=h("div",{},[h("div",{cls:"rk",text:String(r.rank)})]);if(r.orig_rank!=null)box.appendChild(h("div",{cls:"rk-orig",text:"原 #"+r.orig_rank}));return box}
function ghTagEls(r){var out=[];(r.tags||[]).forEach(function(t){out.push(h("span",{cls:"tag",text:String(t)}))});if(r.language)out.push(h("span",{cls:"tag",text:String(r.language)}));return out}
function ghCard(r,extraBtns){var intro=ghIntro(r,true),stars=r.stars!=null?String(r.stars):"—",metaKids=[h("span",{cls:"heat",title:"当前星数",text:"★ "+stars})],d=ghDelta(r);
 if(d)metaKids.push(h("span",{text:d}));
 if(r.stars_7d!=null&&r.board==="hot")metaKids.push(h("span",{text:"7日 +"+String(r.stars_7d)}));
 ghTagEls(r).forEach(function(tg){metaKids.push(tg)});
 if(r.mark_at)metaKids.push(h("span",{text:"标记于 "+jst(r.mark_at)}));
 var body=h("div",{},[h("h3",{cls:"ttl"},[ghNameEl(r.full_name,r.url)])]);
 if(intro){var p=h("p",{cls:"gh-sum"});p.textContent=intro;p.title=intro;body.appendChild(p)}
 body.appendChild(h("div",{cls:"meta"},metaKids));
 var ops=ghMarkBtns(r.full_name,r.mark_state);
 (extraBtns||[]).forEach(function(b){ops.appendChild(b)});
 body.appendChild(ops);
 var kids=[];
 if(!r.no_rank)kids.push(ghRankBox(r));
 kids.push(body);
 return h("li",{cls:"card"+(r.no_rank?"":(" r"+r.rank))+(r.no_rank?" gh-card-norank":"")},kids)}
function ghCount(state){var n=0;Object.keys(MK_STORE.items).forEach(function(k){var it=MK_STORE.items[k];if(it.state!==state)return;if(ghRepoBlocked(ghMarkFields(k,it)))return;n++});return n}
function ghListView(kind,box){box.textContent="";
 var items=[];Object.keys(MK_STORE.items).forEach(function(k){var it=MK_STORE.items[k];if(it.state!==kind)return;if(ghRepoBlocked(ghMarkFields(k,it)))return;var snap=it.snap||{},pub=ghCatalog()[k],name=(snap.full_name||(pub&&pub.full_name)||k),url=snap.url||(pub&&pub.url)||"",summary=(snap.summary&&String(snap.summary).trim())||"",desc=(snap.description&&String(snap.description).trim())||"",intro=summary||desc||"";items.push({key:k,it:it,name:name,url:url,intro:intro})});
 items.sort(function(a,b){return String(a.name).localeCompare(String(b.name))});
 if(!items.length){var emp=h("div",{cls:"emp"});emp.textContent="还没有标记为「"+(MK_LABELS[kind]||kind)+"」的项目。点榜单条目上的按钮即可加入，保存在本机浏览器。";box.appendChild(emp);return}
 box.appendChild(h("h2",{text:(MK_LABELS[kind]||kind)+"（"+items.length+"）"}));
 var ol=h("ol",{cls:"top10",id:"gh-mark-list"});
 items.forEach(function(row){var snap=row.it.snap||{},pub=ghCatalog()[row.key],cancel=h("button",{cls:"btn",type:"button",dataset:{ghun:row.name}});cancel.textContent="取消标记";
  var rec={full_name:row.name,url:row.url,list_intro:row.intro,description:row.intro||"",stars:snap.stars!=null?snap.stars:(pub&&pub.stars),language:snap.language||(pub&&pub.language)||"",tags:(pub&&pub.tags)||[],board:"all",no_rank:true,mark_state:row.it.state,mark_at:row.it.at||""};
  ol.appendChild(ghCard(rec,[cancel]))});
 box.appendChild(ol)}
function ghFillBar(el,opts){el.textContent="";opts.forEach(function(o){var b=h("button",{cls:"chip",type:"button","aria-selected":o.on?"true":"false",dataset:o.data});b.appendChild(document.createTextNode(o.label));if(o.n!=null){var i=h("i");i.textContent=String(o.n);b.appendChild(i)}el.appendChild(b)})}
function ghStatusMsgs(){var note=document.getElementById("gh-status");note.textContent="";
 function add(cls,id,role,text){var p=h("p",{cls:cls});if(id)p.id=id;if(role)p.setAttribute("role",role);p.textContent=text;note.appendChild(p)}
 if(!mkPersistOk)add("warn","gh-persist","status",MK_SAVE_MSG);
 if(GH&&GH.window_note)add("warn",null,"status",GH.window_note);
 add("tiny","gh-note",null,"标记保存在本机浏览器，不会上传。")}
function ghInit(){ghRender()}
function ghRender(){var root=document.getElementById("gh-mod");if(!root)return;
 var boards=(GH&&GH.boards)||{};
 var GH_CATS=["AI","开发工具","前端","后端","移动","DevOps","数据","安全","系统","文档","其他"];
 var lists=document.getElementById("gh-lists");
 if(lists)ghFillBar(lists,MK_ORDER.map(function(k){return{label:MK_LABELS[k],n:ghCount(k),on:ghList===k,data:{ghl:k}}}));
 ghFillBar(document.getElementById("gh-boards"),GH_BOARDS.map(function(b){return{label:b.label,n:ghUnmarked(boards[b.id]||[]).length,on:ghBoard===b.id&&!ghList,data:{ghb:b.id}}}));
 var catBar=document.getElementById("gh-cats");
 if(ghList){catBar.textContent="";catBar.hidden=true}else{catBar.hidden=false;ghFillBar(catBar,["全部"].concat(GH_CATS).map(function(c){return{label:c,on:ghCat===c,data:{ghc:c}}}))}
 ghStatusMsgs();
 var box=document.getElementById("gh-main");
 if(ghList){ghListView(ghList,box);return}
 var unmarked=ghUnmarked(boards[ghBoard]||[]);
 var shown=ghShown(boards[ghBoard]||[],ghCat,GH_SHOW);
 if(ghCat==="全部"&&unmarked.length<GH_SHOW){var tip=h("p",{cls:"warn",id:"gh-reserve",role:"status"});tip.textContent="备用已用完，等下次刷新";document.getElementById("gh-status").appendChild(tip)}
 var missing=0;shown.forEach(function(r){if(!ghZh(r))missing++});
 if(missing){var p=h("p",{cls:"tiny"});p.textContent="部分项目尚无中文简介";document.getElementById("gh-status").appendChild(p)}
 box.textContent="";
 if(!shown.length){var emp=h("div",{cls:"emp"});emp.textContent=ghCat==="全部"?"本小时暂无上榜项目":"本小时该类别暂无上榜项目";box.appendChild(emp);return}
 var top=h("ol",{cls:"top10",id:"gh-top"});shown.slice(0,10).forEach(function(r){top.appendChild(ghCard(r))});box.appendChild(top);
 var rest=shown.slice(10,20);if(rest.length){var ol=h("ol",{cls:"top10",id:"gh-rest"});rest.forEach(function(r){ol.appendChild(ghCard(r))});box.appendChild(ol)}}
window.addEventListener("storage",function(e){if(e.key===MK_KEY){MK_STORE=mkLoad();mkPersistOk=true;ghRender()}});
ghInit();
})();
