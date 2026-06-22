// ── Preview de imagen al subir ──
document.querySelectorAll('input[type="file"][data-preview]').forEach(input => {
  const previewId = input.dataset.preview;
  input.addEventListener('change', () => {
    const file = input.files[0];
    if (!file) return;
    const img = document.getElementById(previewId);
    if (!img) return;
    img.src = URL.createObjectURL(file);
    img.style.display = 'block';
  });
});

// ── QR code modal ──
function abrirQR(nombre, url) {
  const modal = document.getElementById('qr-modal');
  if (!modal) return;
  document.getElementById('qr-nombre').textContent = nombre;
  document.getElementById('qr-link').textContent = url;
  document.getElementById('qr-link').href = url;
  const canvas = document.getElementById('qr-canvas');
  canvas.innerHTML = '';
  if (window.QRCode) {
    new QRCode(canvas, { text: url, width: 200, height: 200, correctLevel: QRCode.CorrectLevel.M });
  }
  modal.classList.add('abierto');
}
function cerrarQR() {
  const modal = document.getElementById('qr-modal');
  if (modal) modal.classList.remove('abierto');
}
document.getElementById('qr-modal')?.addEventListener('click', e => {
  if (e.target === document.getElementById('qr-modal')) cerrarQR();
});

// ── Copiar al portapapeles ──
function copiar(texto, btn) {
  navigator.clipboard.writeText(texto).then(() => {
    const orig = btn.textContent;
    btn.textContent = '¡Copiado!';
    btn.style.background = '#059669';
    btn.style.color = '#fff';
    setTimeout(() => { btn.textContent = orig; btn.style.background = ''; btn.style.color = ''; }, 2000);
  });
}

// ── Carta: carrito drawer ──
const overlay  = document.getElementById('carrito-overlay');
const btnVer   = document.getElementById('btn-ver-carrito');
const btnCerrar = document.getElementById('btn-cerrar-carrito');

btnVer?.addEventListener('click',    () => overlay?.classList.add('abierto'));
btnCerrar?.addEventListener('click', () => overlay?.classList.remove('abierto'));
overlay?.addEventListener('click',   e => { if (e.target === overlay) overlay.classList.remove('abierto'); });

// ── Carta: scroll a sección de categoría ──
document.querySelectorAll('.cat-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const target = document.getElementById('cat-' + tab.dataset.cat);
    if (!target) return;
    const offset = 130;
    const y = target.getBoundingClientRect().top + window.scrollY - offset;
    window.scrollTo({ top: y, behavior: 'smooth' });
  });
});

// ── Carta: highlight categoría activa al hacer scroll ──
const catSecciones = document.querySelectorAll('.cat-seccion');
const catTabs      = document.querySelectorAll('.cat-tab');
if (catSecciones.length) {
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const id  = entry.target.id.replace('cat-', '');
        catTabs.forEach(t => t.classList.toggle('activa', t.dataset.cat === id));
        // scroll tab into view
        const activeTab = document.querySelector(`.cat-tab[data-cat="${id}"]`);
        activeTab?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
      }
    });
  }, { rootMargin: '-130px 0px -60% 0px', threshold: 0 });

  catSecciones.forEach(s => observer.observe(s));
}

// ── Auto-refresh para página de orden ──
if (document.getElementById('orden-estado-page')) {
  setTimeout(() => location.reload(), 30000);
}
