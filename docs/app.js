'use strict';
const root = document.documentElement;
const themeButton = document.getElementById('theme-toggle');
function setTheme(theme) {
  root.dataset.theme = theme;
  themeButton.setAttribute('aria-pressed', String(theme === 'dark'));
  themeButton.setAttribute('aria-label', theme === 'dark' ? 'Ativar tema claro' : 'Ativar tema escuro');
  document.querySelector('meta[name="theme-color"]').content = theme === 'dark' ? '#151516' : '#f3f2ed';
}
try { if (localStorage.getItem('adny-separador-theme') === 'dark') setTheme('dark'); } catch (_) {}
themeButton.addEventListener('click', () => {
  const theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
  setTheme(theme);
  try { localStorage.setItem('adny-separador-theme', theme); } catch (_) {}
});
const menuButton = document.querySelector('.menu-toggle');
const menu = document.getElementById('mobile-nav');
menuButton.addEventListener('click', () => {
  menu.hidden = !menu.hidden;
  menuButton.setAttribute('aria-expanded', String(!menu.hidden));
  menuButton.setAttribute('aria-label', menu.hidden ? 'Abrir menu' : 'Fechar menu');
});
menu.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
  menu.hidden = true; menuButton.setAttribute('aria-expanded', 'false'); menuButton.setAttribute('aria-label', 'Abrir menu');
}));
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !menu.hidden) menuButton.click(); });
const study = window.ADNY_ARARA;
const channels = study.channels;
const controls = document.getElementById('channel-controls');
const canvas = document.getElementById('ink-study');
const context = canvas.getContext('2d');
const status = document.getElementById('channel-status');
let ready = false;
const images = new Map();
const buttons = new Map();
let resultImage;
function updateStudy() {
  if (!ready) return;
  const active = channels.filter(channel => buttons.get(channel.key).getAttribute('aria-pressed') === 'true');
  context.globalCompositeOperation = 'source-over';
  context.fillStyle = '#000'; context.fillRect(0, 0, canvas.width, canvas.height);
  if (active.length === channels.length) {
    context.drawImage(resultImage, 0, 0, canvas.width, canvas.height);
    status.textContent = '9 CANAIS ATIVOS / PRÉVIA SALVA NO PSD';
  } else {
    for (const channel of active) context.drawImage(images.get(channel.key), 0, 0, canvas.width, canvas.height);
    status.textContent = active.length + (active.length === 1 ? ' CANAL ATIVO' : ' CANAIS ATIVOS') + ' / SOBREPOSIÇÃO ILUSTRATIVA';
  }
}
channels.forEach(channel => {
  const button = document.createElement('button'); button.type = 'button'; button.className = 'channel-control real-channel';
  button.disabled = true; button.setAttribute('aria-pressed', 'true');
  button.setAttribute('aria-label', 'Mostrar ou ocultar canal ' + channel.name);
  const thumbnail = document.createElement('img'); thumbnail.src = channel.thumb; thumbnail.width = 180; thumbnail.height = 120; thumbnail.alt = ''; thumbnail.loading = 'eager';
  const swatch = document.createElement('i'); swatch.style.setProperty('--swatch', 'rgb(' + channel.color.join(',') + ')'); swatch.setAttribute('aria-hidden', 'true');
  const name = document.createElement('span'); name.textContent = channel.name; button.append(thumbnail, swatch, name);
  button.addEventListener('click', () => {
    button.setAttribute('aria-pressed', String(button.getAttribute('aria-pressed') !== 'true')); updateStudy();
  }); buttons.set(channel.key, button); controls.append(button);
});
function loadStudyImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image(); image.onload = () => resolve(image); image.onerror = () => reject(new Error('Imagem indisponível: ' + url)); image.src = url;
  });
}
(async () => {
  try {
    resultImage = await loadStudyImage(study.result);
    context.drawImage(resultImage, 0, 0, canvas.width, canvas.height);
    await Promise.all(channels.map(async channel => images.set(channel.key, await loadStudyImage(channel.plate))));
    ready = true; buttons.forEach(button => button.disabled = false); updateStudy();
  } catch (error) {
    status.textContent = 'NÃO FOI POSSÍVEL CARREGAR TODOS OS CANAIS. RECARREGUE A PÁGINA.';
    console.error(error);
  }
})();
document.getElementById('reset-inks').addEventListener('click', () => {
  buttons.forEach(button => button.setAttribute('aria-pressed', 'true')); updateStudy();
});
document.querySelectorAll('[data-download]').forEach(link => {
  const url = window.ADNY_SITE?.downloads?.[link.dataset.download]; if (!url) return;
  const resolved = new URL(url, location.href); if (!['http:', 'https:', 'file:'].includes(resolved.protocol)) return;
  link.href = resolved.href;
});
function updateScroll() {
  const total = document.documentElement.scrollHeight - innerHeight;
  document.getElementById('scroll-marker').style.top = (total > 0 ? scrollY / total * 100 : 0) + '%';
}
addEventListener('scroll', updateScroll, {passive:true}); addEventListener('resize', updateScroll); updateScroll();
