'use strict';
const $ = id => document.getElementById(id);
const canvas=$('canvas'), ctx=canvas.getContext('2d'), wrap=$('canvas-wrap');
const cn={'Person':'人员','Hardhat':'安全帽','Safety Vest':'反光衣','NO-Hardhat':'未戴安全帽（头部）','NO-Safety Vest':'未穿反光衣（上身）'};
const colors=['#f59e0b','#d946ef','#22c55e','#ef4444','#38bdf8','#a78bfa'];
let classes=[],images=[],index=-1,boxes=[],selected=-1,image=null,scale=1,dirty=false,busy=false;
let version='',reviewed=[],undo=[],drawing=null,pan=null,space=false,raw=false,saveTail=Promise.resolve();
const nameOf=b=>cn[classes[b.cls]]||classes[b.cls];
const base=name=>name.replace(/\.[^.]+$/,'');
const status=(s,kind='')=>{$('status').textContent=s;$('status').className=kind;};
const report=e=>{status(e.message||String(e),'error');};
const controlIds=['prev','next','save','complete','image-select','class-select','zoom','fit','person-focus','focus','helmet','vest','original','undo','export','discard'];
function enable(){for(const id of controlIds)$(id).disabled=busy||!image; $('reload').disabled=busy;}
async function api(url,options={}){const r=await fetch(url,{cache:'no-store',...options});const data=await r.json();if(!r.ok)throw Error(data.message||`本地服务错误 ${r.status}`);return data;}
function parse(text){return text.split(/\r?\n/).map(s=>s.trim()).filter(Boolean).map(line=>{const p=line.split(/\s+/).map(Number);if(p.length!==5||!p.every(Number.isFinite)||!Number.isInteger(p[0])||p[0]<0||p[0]>=classes.length||p.slice(1).some(v=>v<0||v>1)||p[3]<=0||p[4]<=0)throw Error('标签格式异常，请保留文件并联系开发人员');return{cls:p[0],cx:p[1],cy:p[2],w:p[3],h:p[4]};});}
function serialize(){return boxes.map(b=>`${b.cls} ${[b.cx,b.cy,b.w,b.h].map(x=>x.toFixed(6)).join(' ')}`).join('\n')+(boxes.length?'\n':'');}
function save(){
  const run=saveTail.then(async()=>{if(!dirty||index<0)return;const name=base(images[index])+'.txt';const text=serialize();const data=await api('/api/labels/'+encodeURIComponent(name),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,version,reviewed_classes:reviewed})});version=data.version;dirty=false;render();status(`已保存：${images[index]} · ${boxes.length} 个框（包含隐藏框）`,'success');});
  saveTail=run.catch(()=>{});return run;
}
async function guarded(fn){if(busy)return;busy=true;enable();try{await fn();}catch(e){report(e);}finally{busy=false;enable();}}
function visible(b){return!raw&&!(classes[b.cls]==='Person'&&$('hide-person').checked)&&(!$('current-only').checked||b.cls===Number($('class-select').value));}
function checkpoint(){undo.push(structuredClone(boxes));if(undo.length>30)undo.shift();dirty=true;reviewed=[];}
function edit(fn){return guarded(async()=>{checkpoint();fn();selected=-1;render();await save();});}
function point(e){const r=canvas.getBoundingClientRect();return{x:Math.max(0,Math.min(image.naturalWidth,(e.clientX-r.left)/scale)),y:Math.max(0,Math.min(image.naturalHeight,(e.clientY-r.top)/scale))};}
function draw(){if(!image)return;canvas.width=Math.round(image.naturalWidth*scale);canvas.height=Math.round(image.naturalHeight*scale);ctx.drawImage(image,0,0,canvas.width,canvas.height);ctx.lineWidth=1;ctx.font='12px system-ui';
  boxes.forEach((b,i)=>{if(!visible(b))return;const x=(b.cx-b.w/2)*canvas.width,y=(b.cy-b.h/2)*canvas.height,w=b.w*canvas.width,h=b.h*canvas.height;ctx.strokeStyle=colors[b.cls%colors.length];ctx.setLineDash(i===selected?[4,3]:[]);ctx.strokeRect(x,y,w,h);ctx.setLineDash([]);if($('show-names').checked){const t=nameOf(b);const ty=y<17?y+h+14:y-4;ctx.lineWidth=3;ctx.strokeStyle='#111827';ctx.strokeText(t,x,ty);ctx.fillStyle='#fff';ctx.fillText(t,x,ty);ctx.lineWidth=1;}});
  if(drawing){ctx.strokeStyle='#fff';ctx.setLineDash([5,3]);ctx.strokeRect(drawing.a.x*scale,drawing.a.y*scale,(drawing.b.x-drawing.a.x)*scale,(drawing.b.y-drawing.a.y)*scale);ctx.setLineDash([]);}
}
function render(){draw();$('counts').textContent=`第 ${index+1}/${images.length} 张 · 共 ${boxes.length} 框 · 人员 ${boxes.filter(b=>classes[b.cls]==='Person').length}（隐藏也保留）`;$('coverage').textContent=reviewed.length?(dirty?'本帧帽/衣完成标记待保存（尚未保存成功）':'本帧帽/衣已标完'):'本帧帽/衣尚未确认完成';$('boxes').replaceChildren();
  boxes.forEach((b,i)=>{if(!visible(b))return;const row=document.createElement('div');row.className='box-row'+(i===selected?' selected':'');const dot=document.createElement('i');dot.className='swatch';dot.style.background=colors[b.cls%colors.length];const text=document.createElement('span');text.textContent=`${i+1}. ${nameOf(b)}`;row.onclick=()=>{selected=i;render();};const del=document.createElement('button');del.textContent='删除';del.onclick=e=>{e.stopPropagation();edit(()=>boxes.splice(i,1));};row.append(dot,text,del);$('boxes').append(row);});
  const focusValue=$('person-focus').value;$('person-focus').replaceChildren();boxes.forEach((b,i)=>{if(classes[b.cls]!=='Person')return;const o=document.createElement('option');o.value=i;o.textContent=`人员框 ${i+1}（${Math.round(b.w*image.naturalWidth)}×${Math.round(b.h*image.naturalHeight)}像素）`;$('person-focus').append(o);});if([...$('person-focus').options].some(o=>o.value===focusValue))$('person-focus').value=focusValue;
}
function setScale(value,center){scale=Math.max(.05,Math.min(10,value));$('zoom').value=Math.round(scale*100);$('zoom-value').textContent=Math.round(scale*100)+'%';draw();if(center){wrap.scrollLeft=center.x*scale-wrap.clientWidth/2;wrap.scrollTop=center.y*scale-wrap.clientHeight/2;}}
function fit(){setScale(Math.min(1,wrap.clientWidth/image.naturalWidth,wrap.clientHeight/image.naturalHeight));wrap.scrollLeft=0;wrap.scrollTop=0;}
function populate(){
  $('class-select').replaceChildren();const priority=[2,11,5,7,8];[...priority,...classes.map((_,i)=>i).filter(i=>!priority.includes(i))].filter(i=>i<classes.length).forEach(i=>{const o=document.createElement('option');o.value=i;o.textContent=`${i}: ${cn[classes[i]]||classes[i]}`;$('class-select').append(o);});
  $('image-select').replaceChildren();images.forEach((name,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`${i+1}/${images.length} · ${name}`;$('image-select').append(o);});
  if(index>=0)$('image-select').value=String(index);
}
async function load(newIndex){
  drawing=null;pan=null;draw();
  try{await save();const target=Math.max(0,Math.min(images.length-1,newIndex));const name=images[target];status(`正在读取 ${name}…`);const data=await api('/api/labels/'+encodeURIComponent(base(name)+'.txt'));const parsed=parse(data.text);const nextImage=new Image();nextImage.src='/api/images/'+encodeURIComponent(name);await nextImage.decode();index=target;boxes=parsed;version=data.version;reviewed=data.reviewed_classes||[];dirty=false;undo=[];selected=-1;image=nextImage;$('image-select').value=String(index);render();fit();status(`${name} · 已加载 ${boxes.length} 个框；人员框已保留。`,'success');}
  catch(e){if(index>=0)$('image-select').value=String(index);throw e;}
}
async function open(){
  await save();const data=await api('/api/info');if(data.api_version!==2)throw Error('标注服务仍是旧版本，请重新启动本地标注后刷新；暂未写入标签。');if(!Array.isArray(data.classes)||!Array.isArray(data.images)||!data.images.length)throw Error('标注包没有图片');
  const previous={classes,images,classChoice:$('class-select').value};classes=data.classes;images=data.images;populate();$('class-select').value=String(Math.min(2,classes.length-1));
  try{await load(Math.max(0,index));}catch(e){classes=previous.classes;images=previous.images;populate();$('class-select').value=previous.classChoice;throw e;}
}
$('reload').onclick=()=>guarded(open);$('prev').onclick=()=>guarded(()=>load(index-1));$('next').onclick=()=>guarded(()=>load(index+1));$('image-select').onchange=()=>guarded(()=>load(Number($('image-select').value)));$('save').onclick=()=>guarded(async()=>{await save();status(`当前标签已保存：${images[index]}（含隐藏人员框）`,'success');});
$('complete').onclick=()=>guarded(async()=>{reviewed=[2,5,7,11];dirty=true;await save();if(index+1<images.length)await load(index+1);else{render();status('最后一帧帽衣标注已保存。','success');}});
for(const id of['hide-person','current-only','show-names'])$(id).onchange=render;
$('class-select').onchange=render;$('helmet').onclick=()=>{$('class-select').value='2';render();};$('vest').onclick=()=>{$('class-select').value='11';render();};
$('zoom').oninput=()=>{const center={x:(wrap.scrollLeft+wrap.clientWidth/2)/scale,y:(wrap.scrollTop+wrap.clientHeight/2)/scale};setScale(Number($('zoom').value)/100,center);};$('fit').onclick=fit;
$('focus').onclick=()=>{const b=boxes[Number($('person-focus').value)];if(!b)return;setScale(Math.min(10,wrap.clientHeight*.65/(b.h*image.naturalHeight)),{x:b.cx*image.naturalWidth,y:b.cy*image.naturalHeight});};
$('original').onpointerdown=()=>{raw=true;draw();};window.addEventListener('pointerup',()=>{if(raw){raw=false;draw();}});
$('undo').onclick=()=>guarded(async()=>{if(!undo.length)return;boxes=undo.pop();dirty=true;reviewed=[];selected=-1;render();await save();});
$('export').onclick=()=>{const a=document.createElement('a');const url=URL.createObjectURL(new Blob([serialize()],{type:'text/plain;charset=utf-8'}));a.href=url;a.download=base(images[index])+'.draft.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('discard').onclick=()=>{if(dirty&&!confirm('将丢弃本页面尚未保存的修改。需要保留时请先下载标签草稿。是否重读磁盘标签？'))return;guarded(async()=>{dirty=false;await load(index);});};
canvas.addEventListener('pointerdown',e=>{if(!image||busy)return;canvas.setPointerCapture(e.pointerId);if(space||e.button===1){pan={x:e.clientX,y:e.clientY,left:wrap.scrollLeft,top:wrap.scrollTop};return;}if(e.button!==0)return;const p=point(e);drawing={a:p,b:p,frame:index,cls:Number($('class-select').value)};draw();});
canvas.addEventListener('pointermove',e=>{if(pan){wrap.scrollLeft=pan.left-(e.clientX-pan.x);wrap.scrollTop=pan.top-(e.clientY-pan.y);}else if(drawing){drawing.b=point(e);draw();}});
canvas.addEventListener('pointerup',e=>{if(pan){pan=null;return;}if(!drawing)return;const gesture=drawing;const a=gesture.a,b=point(e);drawing=null;if(gesture.frame!==index){draw();return;}const w=Math.abs(a.x-b.x),h=Math.abs(a.y-b.y);if(w<1||h<1){draw();return;}const box={cls:gesture.cls,cx:(a.x+b.x)/2/image.naturalWidth,cy:(a.y+b.y)/2/image.naturalHeight,w:w/image.naturalWidth,h:h/image.naturalHeight};edit(()=>boxes.push(box));});
canvas.addEventListener('pointercancel',()=>{drawing=null;pan=null;draw();});
document.addEventListener('keydown',e=>{if(e.code==='Space'){space=true;canvas.style.cursor='grab';if(e.target.tagName!=='BUTTON')e.preventDefault();return;}if(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;const k=e.key.toLowerCase();if(k==='x'){raw=true;draw();}if(busy)return;if(k==='a')guarded(()=>load(index-1));if(k==='d')guarded(()=>load(index+1));if(k==='s'){e.preventDefault();guarded(save);}if(k==='h'){$('class-select').value='2';render();}if(k==='v'){$('class-select').value='11';render();}if(e.key==='Delete'&&selected>=0)edit(()=>boxes.splice(selected,1));});
document.addEventListener('keyup',e=>{if(e.code==='Space'){space=false;canvas.style.cursor='crosshair';}if(e.key.toLowerCase()==='x'){raw=false;draw();}});
window.addEventListener('blur',()=>{space=false;raw=false;pan=null;drawing=null;draw();});
window.addEventListener('beforeunload',e=>{if(dirty||busy){e.preventDefault();e.returnValue='';}});
guarded(open);
