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
 document.getElementById('foot').innerHTML='<p id="basis">排序依据：名次、互动数、跨源数，不含点击率</p><p>热度 = 100 ×（0.65×互动分 + 0.35×跨源分）× 0.5^(小时/8)。中文标题与摘要为人工维护，没有记录时显示原标题。</p>'}
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
})();
