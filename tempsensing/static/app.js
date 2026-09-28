const $ = (selector) => document.querySelector(selector);
let state = null, history = [], metric = 'temperature_c', bucket = 60, refreshing = false;
const colors = new Map();
const color = (id) => { if (!colors.has(id)) colors.set(id, colors.size % 6); return `c${colors.get(id)}`; };
const number = (value, digits = 1) => value == null ? '—' : Number(value).toLocaleString('es-UY', {minimumFractionDigits: digits, maximumFractionDigits: digits});
function el(tag, text, className) { const node = document.createElement(tag); if (text != null) node.textContent = text; if (className) node.className = className; return node; }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  if (!response.ok) throw new Error(`No se pudo completar la operación (${response.status}).`);
  return response.json();
}
function age(timestamp) { if (!timestamp) return 'Sin lecturas'; const minutes = Math.max(0, Math.floor((state.now-timestamp)/60)); return minutes < 1 ? 'Hace unos segundos' : minutes < 60 ? `Hace ${minutes} min` : `Hace ${Math.floor(minutes/60)} h`; }
function render() {
  const active = state.sensors.filter(s => s.enabled);
  $('#connection').textContent = state.collector_online ? 'Recolector conectado' : 'Recolector desconectado';
  $('#connection').classList.toggle('online', state.collector_online);
  $('#notice').hidden = state.collector_online;
  $('#notice').textContent = 'El recolector no está respondiendo. El historial sigue disponible; las lecturas se reanudan cuando vuelva a conectarse.';
  $('#empty').hidden = active.length > 0;
  $('#schedule').textContent = `Cada ${state.interval/60} min · Historial de 365 días`;
  $('#cards').replaceChildren(...active.map(s => {
    const stale = !s.timestamp || state.now-s.timestamp > state.interval*2+60;
    const card = el('article', null, 'card'), top = el('div', null, 'card-top'), room = el('div', null, 'room');
    room.append(el('span', null, `dot ${color(s.id)}`), el('span', s.name));
    const badge = state.active_sensor === s.id ? 'Consultando' : s.error ? 'Sin respuesta' : !s.timestamp ? 'Esperando' : stale ? 'Sin señal' : 'Actualizado';
    top.append(room, el('span', badge, `badge ${stale || s.error ? 'stale' : ''}`));
    const metrics = el('div', null, 'metrics'), temp = el('div', number(s.temperature_c), 'temp'), humid = el('div', `${number(s.humidity_percent,0)}%`, 'humidity');
    temp.append(el('small','°C')); humid.append(el('small','humedad')); metrics.append(temp, humid);
    const bottom = el('div', null, 'card-bottom'); bottom.append(el('span', age(s.timestamp)), el('span', s.battery_voltage == null ? 'Batería —' : `Batería ${number(s.battery_voltage,2)} V`));
    card.append(top, metrics, bottom);
    if (s.error) card.append(el('p', s.error, 'error-detail'));
    return card;
  }));
  renderScan();
  if (!$('#settings-dialog').open || !$('#devices').contains(document.activeElement)) renderDevices();
  draw();
}
function renderScan() {
  const busy = ['pending','scanning'].includes(state.scan_state);
  $('#scan').disabled = busy && state.collector_online;
  $('#scan-status').textContent = state.scan_state === 'scanning' ? 'Buscando durante 30 segundos…' : state.scan_state === 'pending' ? 'Búsqueda en cola…' : state.scan_state === 'error' ? `Bluetooth: ${state.scan_error}` : `${state.scan_count} sensores encontrados en la última búsqueda`;
}
function renderDevices() {
  const devices = state.sensors.map(s => {
    const item = el('div', null, 'device'), field = el('div', null, 'field'), input = el('input');
    input.value = s.name; input.maxLength = 60; input.id = `name-${s.id}`; input.required = true;
    const label = el('label','Ambiente'); label.htmlFor = input.id; field.append(label, input);
    const actions = el('div', null, 'device-actions'), save = el('button','Renombrar','secondary'), toggle = el('button',s.enabled ? 'Pausar' : 'Activar',s.enabled ? 'secondary' : 'primary');
    async function update(enabled) {
      if (!input.value.trim()) { input.focus(); return; }
      save.disabled = toggle.disabled = true;
      try { await api(`/api/sensors/${encodeURIComponent(s.id)}`, {name: input.value, enabled}); document.activeElement.blur(); await refresh(); }
      catch (error) { $('#settings-message').textContent = error.message; }
      finally { save.disabled = toggle.disabled = false; }
    }
    save.onclick = () => update(Boolean(s.enabled)); toggle.onclick = () => update(!s.enabled);
    actions.append(save,toggle); item.append(field, actions, el('small', `${s.model} · ${s.id} · ${s.rssi ?? '—'} dBm`)); return item;
  });
  $('#devices').replaceChildren(...(devices.length ? devices : [el('p', 'Todavía no encontramos sensores. Verificá que Bluetooth esté encendido y acercá los sensores al equipo.', 'hint')]));
}
function svg(tag, attrs, text) { const node = document.createElementNS('http://www.w3.org/2000/svg',tag); for (const [key,value] of Object.entries(attrs)) node.setAttribute(key,value); if (text != null) node.textContent = text; return node; }
function draw() {
  if (!state) return;
  const chart = $('#chart'), sensors = state.sensors.filter(s => s.enabled), ids = new Set(sensors.map(s=>s.id));
  const points = history.filter(p=>ids.has(p.sensor_id));
  const width = Math.max(280, chart.clientWidth), hours = Number($('#range').value), end = state.now, start = end-hours*3600, left = 45, right = width-15, top = 15, bottom = 270;
  chart.setAttribute('viewBox', `0 0 ${width} 310`);
  const values = points.map(p=>p[metric]);
  let min = values.length ? Math.min(...values) : metric === 'temperature_c' ? 10 : 0;
  let max = values.length ? Math.max(...values) : metric === 'temperature_c' ? 30 : 100;
  const padding = Math.max((max-min)*.15, metric === 'temperature_c' ? 1 : 3); min = Math.floor(min-padding); max = Math.ceil(max+padding);
  if (metric === 'humidity_percent') { min=Math.max(0,min); max=Math.min(100,max); }
  const x = t=>left+(t-start)/(end-start)*(right-left), y = v=>bottom-(v-min)/(max-min)*(bottom-top);
  chart.replaceChildren(); chart.setAttribute('aria-label', `Historial de ${metric === 'temperature_c' ? 'temperatura' : 'humedad'}, ${points.length} puntos. Las lecturas exactas están disponibles en Exportar CSV.`);
  for (let i=0;i<=4;i++) { const v=min+(max-min)*i/4, yy=y(v); chart.append(svg('line',{x1:left,x2:right,y1:yy,y2:yy,class:'grid'}),svg('text',{x:left-10,y:yy+4,'text-anchor':'end'},number(v,metric==='temperature_c'?1:0))); }
  const ticks = width < 500 ? 2 : 4;
  for (let i=0;i<=ticks;i++) { const t=start+(end-start)*i/ticks; const date=new Date(t*1000); chart.append(svg('text',{x:x(t),y:300,'text-anchor':i===0?'start':i===ticks?'end':'middle'},hours>24?date.toLocaleDateString('es-UY',{day:'numeric',month:'short'}):date.toLocaleTimeString('es-UY',{hour:'2-digit',minute:'2-digit'}))); }
  const maxGap = Math.max(state.interval*2.5, bucket*2.5);
  for (const sensor of sensors) {
    const series = points.filter(p=>p.sensor_id===sensor.id); let path='', previous=null;
    for (const point of series) { const move=!previous || point.timestamp-previous.timestamp>maxGap; path+=`${move?'M':'L'}${x(point.timestamp).toFixed(2)},${y(point[metric]).toFixed(2)} `; previous=point; }
    if (path) chart.append(svg('path',{d:path,class:`line ${color(sensor.id)}`}));
    for (const point of series) { const dot=svg('circle',{cx:x(point.timestamp),cy:y(point[metric]),r:series.length>50?1:3,class:color(sensor.id)}); dot.append(svg('title',{},`${sensor.name}: ${number(point[metric])}${metric==='temperature_c'?'°C':'%'} · ${new Date(point.timestamp*1000).toLocaleString('es-UY')}`)); chart.append(dot); }
  }
  $('#chart-empty').hidden=points.length>0;
  $('#legend').replaceChildren(...sensors.map(s=>{const item=el('span'); item.append(el('i',null,`dot ${color(s.id)}`),document.createTextNode(s.name)); return item;}));
  $('#aggregation').textContent = `Promedios por ${Math.round(bucket/60)} min · ${points.reduce((sum,p)=>sum+p.samples,0).toLocaleString('es-UY')} lecturas`;
  chart.onpointermove = event => {
    if (!points.length) return;
    const rect=chart.getBoundingClientRect(), target=start+((event.clientX-rect.left)/rect.width*width-left)/(right-left)*(end-start);
    const nearest=points.reduce((a,b)=>Math.abs(a.timestamp-target)<Math.abs(b.timestamp-target)?a:b);
    const sensor=sensors.find(s=>s.id===nearest.sensor_id);
    $('#chart-detail').textContent = `${sensor.name} · ${new Date(nearest.timestamp*1000).toLocaleString('es-UY')} · ${number(nearest.temperature_c)} °C · ${number(nearest.humidity_percent,0)}% humedad`;
  };
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try { const hours=$('#range').value; const [next, data]=await Promise.all([api('/api/status'),api(`/api/history?hours=${hours}`)]); state=next; history=data.points; bucket=data.bucket_seconds; render(); }
  catch (error) { $('#notice').hidden=false; $('#notice').textContent=`No se pudo actualizar la pantalla. ${error.message}`; $('#connection').textContent='Sin conexión'; $('#connection').classList.remove('online'); }
  finally { refreshing=false; }
}
function openSettings() { $('#settings-message').textContent=''; if(state) { $('#interval').value=state.interval; renderDevices(); } $('#settings-dialog').showModal(); }
async function scan() { $('#scan').disabled=true; try { await api('/api/scan',{}); await refresh(); } catch(error) { $('#settings-message').textContent=error.message; $('#scan').disabled=false; } }
$('#manage').onclick=openSettings; $('#close-dialog').onclick=()=>$('#settings-dialog').close();
$('#first-scan').onclick=()=>{openSettings();scan();}; $('#scan').onclick=scan;
$('#range').onchange=()=>{$('#export').href=`/api/export?hours=${$('#range').value}`;refresh();};
for (const [id, key] of [['temperature-tab','temperature_c'],['humidity-tab','humidity_percent']]) {
  $(`#${id}`).onclick=()=>{metric=key; for(const tab of ['temperature-tab','humidity-tab']) { $(`#${tab}`).classList.toggle('selected',tab===id); $(`#${tab}`).setAttribute('aria-pressed',String(tab===id)); } $('#chart-unit').textContent=key==='temperature_c'?'°C':'% HR'; draw();};
}
$('#interval-form').onsubmit=async event=>{event.preventDefault();try{await api('/api/settings',{interval:Number($('#interval').value)});$('#settings-message').textContent='Frecuencia guardada.';await refresh();}catch(error){$('#settings-message').textContent=error.message;}};
refresh(); setInterval(refresh,10000); window.addEventListener('resize',draw);
