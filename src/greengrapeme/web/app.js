"use strict";
let secret="",offset=0,total=0;
const $=id=>document.getElementById(id), limit=40;
function text(parent,tag,value){const n=document.createElement(tag);n.textContent=value==null?"–":String(value);parent.appendChild(n);return n;}
function cell(tr,v){text(tr,"td",v);}
async function request(path,params){
 const u=new URL(path,location.origin);if(params)for(const [k,v] of Object.entries(params))u.searchParams.set(k,String(v));
 const r=await fetch(u,{headers:{"X-Green-Grape-Token":secret},cache:"no-store",credentials:"omit"});
 if(!r.ok)throw Error(r.status===401?"Zugriff verweigert":"Abfragefehler "+r.status);
 return r.json();
}
function error(e){$("error").textContent=e.message||String(e);}
async function overview(){
 const d=await request("/api/overview"),box=$("overview");box.replaceChildren();
 for(const [label,value] of [["Unternehmen",d.opportunities],["Vertriebsaufträge",d.work_items],["Missionen",d.missions],["Sperren",d.suppressions]]){
  const m=text(box,"div","");m.className="metric";text(m,"strong",value);text(m,"span",label);
 }
 const sel=$("offer");sel.replaceChildren();const all=text(sel,"option","Alle Angebote");all.value="";
 for(const offer of d.offers||[]){const o=text(sel,"option",offer.offer_id+" ("+offer.accounts+")");o.value=offer.offer_id;}
}
async function companies(){
 const d=await request("/api/companies",{q:$("search").value,offer:$("offer").value,status:$("status").value,limit,offset});
 total=d.total;$("result-count").textContent=total+" Unternehmen gefunden";
 $("page").textContent=(total?offset+1:0)+"–"+Math.min(total,offset+limit)+" von "+total;
 $("prev").disabled=!offset;$("next").disabled=offset+limit>=total;
 const target=$("companies");target.replaceChildren();
 for(const x of d.items){
  const tr=document.createElement("tr");
  for(const v of [x.company_name,x.offer_id,x.qualification,x.evidence_count,x.suppressed?"Gesperrt":"Nein"])cell(tr,v);
  const td=document.createElement("td"),b=text(td,"button","Details");b.type="button";
  b.addEventListener("click",()=>detail(x.opportunity_id).catch(error));
  tr.appendChild(td);target.appendChild(tr);
 }
 if(!d.items.length){const tr=document.createElement("tr"),td=text(tr,"td","Keine Einträge");td.colSpan=6;target.appendChild(tr);}
}
function pair(parent,name,value){text(parent,"dt",name);text(parent,"dd",value);}
function item(parent,description,url){
 const li=document.createElement("li");text(li,"span",description);
 if(typeof url==="string"&&url.startsWith("https://")){
  text(li,"span"," · ");const a=text(li,"a","Quelle öffnen");a.href=url;a.target="_blank";a.rel="noopener noreferrer";
 }
 parent.appendChild(li);
}
async function detail(id){
 const d=await request("/api/company",{id});$("details").hidden=false;$("company-name").textContent=d.company_name;
 const meta=$("company-meta");meta.replaceChildren();
 for(const [k,v] of [["Discovery-ID",d.opportunity_id],["Angebot",d.offer_id],["Qualifikation",d.qualification],["Identität",d.identity_state],["Kontakterlaubnis",d.contact_authority],["Sperre",d.suppressed?d.suppression_reason:"Keine lokale Sperre"],["Signalpriorität",d.intent_score+"/100 (Heuristik)"]])pair(meta,k,v);
 $("evidence").replaceChildren();for(const e of d.evidence)item($("evidence"),e.kind+": "+e.claim,e.reference);
 $("signals").replaceChildren();for(const s of d.signals)item($("signals"),s.kind+": "+s.claim+" ("+s.observed_at+")",s.evidence_url);
 const b=$("blackberry");b.replaceChildren();
 if(!d.blackberry_research)text(b,"p","Noch keine BlackberryMe-Recherche");
 else{ text(b,"p","Status: "+d.blackberry_research.donor_status+"; Account-Zuordnung: UNVERIFIED");
  for(const r of d.blackberry_research.role_reviews)text(b,"p",r.title+": "+r.classification+" ("+r.score+")");
 }
 $("company-tasks").replaceChildren();for(const t of d.tasks)item($("company-tasks"),t.role+": "+t.action+" — "+t.state);
 $("details").scrollIntoView({behavior:"smooth",block:"start"});
}
async function work(){const d=await request("/api/work");$("work-list").replaceChildren();for(const t of d.items){const tr=document.createElement("tr");for(const v of [t.opportunity_id,t.role,t.action,t.state])cell(tr,v);$("work-list").appendChild(tr);}}
async function missions(){const d=await request("/api/missions");$("missions-list").replaceChildren();for(const m of d.items){const tr=document.createElement("tr");for(const v of [m.mission_id,m.offer_id,m.objective,m.status])cell(tr,v);$("missions-list").appendChild(tr);}}
$("login-form").addEventListener("submit",async e=>{e.preventDefault();secret=$("token").value;$("login-error").textContent="";try{await overview();await companies();$("token").value="";$("login").hidden=true;$("workspace").hidden=false;}catch(e){secret="";$("login-error").textContent=e.message;}});
$("logout").addEventListener("click",()=>{secret="";$("workspace").hidden=true;$("login").hidden=false;$("details").hidden=true;});
$("filters").addEventListener("submit",e=>{e.preventDefault();offset=0;companies().catch(error);});
$("prev").addEventListener("click",()=>{offset=Math.max(0,offset-limit);companies().catch(error);});
$("next").addEventListener("click",()=>{offset+=limit;companies().catch(error);});
$("close-details").addEventListener("click",()=>{$("details").hidden=true;});
for(const b of document.querySelectorAll("[data-view]"))b.addEventListener("click",()=>{
 const view=b.dataset.view;
 for(const v of ["companies","work","missions"]){$(v+"-view").hidden=view!==v;document.querySelector('[data-view="'+v+'"]').setAttribute("aria-current",view===v?"page":"false");}
 ({companies,work,missions})[view]().catch(error);
});