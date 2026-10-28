// The witness page: every figure comes from the open case's exported data (web/data/colombia-2025-07-30.json).
const FORM_URL = '';  // the Google Form, once it is published

const DIRS = ['norte', 'nor-noreste', 'noreste', 'este-noreste', 'este', 'este-sureste', 'sureste', 'sur-sureste', 'sur',
  'sur-suroeste', 'suroeste', 'oeste-suroeste', 'oeste', 'oeste-noroeste', 'noroeste', 'nor-noroeste'];
const dir = az => DIRS[Math.round(((az % 360) + 360) % 360 / 22.5) % 16];
const num = (v, d = 0) => Number(v).toLocaleString('es-CO', {minimumFractionDigits: d, maximumFractionDigits: d});
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

function render(d) {
  const asked = (d.run && d.run.block && d.run.block.request && d.run.block.request.towns) || [];
  const [lon, lat] = d.satellite.lonlat;
  document.getElementById('flash').innerHTML = `durante <span class="num">${num(d.satellite.duration_s, 2)}</span> s, cerca de
    <span class="num">${num(Math.abs(lat), 2)}°</span> ${lat >= 0 ? 'norte' : 'sur'} y <span class="num">${num(Math.abs(lon), 2)}°</span>
    ${lon >= 0 ? 'este' : 'oeste'}, entre Santander, Boyacá y Arauca`;
  const med = d.towns.find(t => t.city === 'Medellín');
  document.getElementById('status').innerHTML = `
    <p>Hasta hoy solo tenemos un video, grabado en Medellín${med ? `, a <span class="num">${med.km}</span> km del destello` : ''}.
    No se puede ubicar en un mapa lo que se ve, ni se sabe desde dónde se grabó, así que no alcanza para calcular la trayectoria.</p>
    ${asked.length ? `<p>Por eso el agente pidió videos desde <b>${asked.map(esc).join(', ').replace(/, ([^,]*)$/, ' y $1')}</b>, y el caso
    queda en espera hasta que lleguen.</p>` : ''}`;
  const rows = d.towns.filter(t => t.sees_it_high)
    .sort((a, b) => (asked.includes(b.city) - asked.includes(a.city)) || a.km - b.km);
  document.getElementById('towns').innerHTML = rows.map(t => `<tr class="${asked.includes(t.city) ? 'asked' : ''}">
    <td>${esc(t.city)}${asked.includes(t.city) ? '<span class="tag">pedido por el agente</span>' : ''}</td>
    <td class="r"><span class="num">${t.km}</span> km</td>
    <td class="r">${dir(t.look_az_deg)}</td>
    <td class="r"><span class="num">${num(t.el_at_40km_deg)}–${num(t.el_at_80km_deg)}°</span></td></tr>`).join('');
  if (FORM_URL) {
    const send = document.getElementById('send');
    send.href = FORM_URL;
    send.removeAttribute('aria-disabled');
    send.target = '_blank';
    send.rel = 'noopener';
    document.getElementById('soon').remove();
  }
}

fetch('data/colombia-2025-07-30.json').then(r => r.json()).then(render).catch(() => {});
document.getElementById('send').addEventListener('click', e => { if (!FORM_URL) e.preventDefault(); });
