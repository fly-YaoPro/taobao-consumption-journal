/* An offline paper journal. The caller supplies the same checked journal data as the page. */
(() => {
  'use strict';

  const COLOR = Object.freeze({
    paper: '#f6f1e7', ink: '#273e4a', yellow: '#f2cd67', rust: '#cf8d73',
    blue: '#bacbdc', sage: '#d5dfc8', muted: '#626f70', rule: '#d8d5c9', white: '#fffdf7'
  });
  const DISPLAY = 'ScrapDisplay, "Noto Sans SC", sans-serif';
  const BODY = 'ScrapBody, "Noto Sans SC", sans-serif';
  const NOTE = 'ScrapNote, "KaiTi", serif';
  const text = value => typeof value === 'string' ? value.trim() : '';
  const date = value => /^\d{4}-\d{2}-\d{2}$/.test(text(value)) ? value : '';
  const imageURL = value => /^data:image\/(?:png|jpeg|webp|gif|avif);base64,[a-z\d+/=\s]+$/i.test(value || '');

  function linesFor(ctx, value, width) {
    const lines = [];
    for (const paragraph of text(value).split(/\r?\n/)) {
      let line = '';
      for (const character of Array.from(paragraph)) {
        if (line && ctx.measureText(line + character).width > width) {
          lines.push(line.trimEnd());
          line = character.trimStart();
        } else line += character;
      }
      lines.push(line.trimEnd());
    }
    return lines;
  }

  function print(ctx, value, x, y, width, { size = 24, lineHeight = size * 1.45,
    maxLines = 3, family = BODY, color = COLOR.ink, weight = '400' } = {}) {
    ctx.font = `${weight} ${size}px ${family}`;
    ctx.fillStyle = color;
    const all = linesFor(ctx, value, width);
    const rows = all.slice(0, maxLines);
    if (all.length > maxLines && rows.length) {
      let last = rows[rows.length - 1];
      while (last && ctx.measureText(last + '…').width > width) last = Array.from(last).slice(0, -1).join('');
      rows[rows.length - 1] = last.replace(/[，、；。\s]+$/, '') + '…';
    }
    rows.forEach((row, index) => ctx.fillText(row, x, y + index * lineHeight));
    return rows.length * lineHeight;
  }

  function roundedPaper(ctx, x, y, width, height, fill, radius = 12, shadow = false) {
    ctx.save();
    if (shadow) {
      ctx.shadowColor = '#273e4a1c';
      ctx.shadowBlur = 18;
      ctx.shadowOffsetY = 6;
    }
    ctx.fillStyle = fill;
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + width - radius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
    ctx.lineTo(x + width, y + height - radius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
    ctx.lineTo(x + radius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  function tape(ctx, x, y, width, color, angle = 0) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(angle);
    ctx.globalAlpha = .82;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(3, 0);
    ctx.lineTo(width, 2);
    ctx.lineTo(width - 3, 30);
    ctx.lineTo(0, 28);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  function shortObservation(value) {
    const clean = text(value).replace(/\s+/g, ' ');
    const firstSentence = clean.match(/^.*?[。！？](?:[”’」』])?/u);
    return firstSentence ? firstSentence[0] : clean;
  }

  function loadImage(asset) {
    return new Promise(resolve => {
      if (!imageURL(asset?.data_url)) return resolve(null);
      const img = new Image();
      let timer;
      function finish(result) {
        clearTimeout(timer);
        img.onload = null;
        img.onerror = null;
        resolve(result);
      }
      img.onload = () => finish(img.naturalWidth > 0 && img.naturalHeight > 0 ? { asset, img } : null);
      img.onerror = () => finish(null);
      timer = setTimeout(() => finish(null), 8000);
      img.src = asset.data_url;
    });
  }

  function photograph(ctx, item, x, y, width, height, background, inset) {
    ctx.fillStyle = background;
    ctx.fillRect(x, y, width, height);
    const { img } = item;
    // Containment preserves the selected product, including tall packaging and transparent cutouts.
    const scale = Math.min((width - inset * 2) / img.naturalWidth, (height - inset * 2) / img.naturalHeight);
    const drawWidth = img.naturalWidth * scale, drawHeight = img.naturalHeight * scale;
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, width, height);
    ctx.clip();
    ctx.drawImage(img, x + (width - drawWidth) / 2, y + (height - drawHeight) / 2, drawWidth, drawHeight);
    ctx.restore();
  }

  function caption(ctx, item, x, y, width, { main = false, demo = false } = {}) {
    const when = date(item.asset.date);
    print(ctx, text(item.asset.caption) || (demo ? '演示物件' : '记录中的物件'), x, y, width, {
      size: main ? 25 : 20, lineHeight: main ? 33 : 27, maxLines: 2, family: NOTE
    });
    if (when) print(ctx, when.replaceAll('-', '.'), x, y + (main ? 67 : 58), width, {
      size: 14, maxLines: 1, color: COLOR.muted
    });
  }

  function photoCard(ctx, item, { x, y, width, height, angle, background, main = false, demo = false }) {
    ctx.save();
    ctx.translate(x + width / 2, y + height / 2);
    ctx.rotate(angle);
    ctx.translate(-width / 2, -height / 2);
    roundedPaper(ctx, 0, 0, width, height, COLOR.white, 7, true);
    const imageHeight = height - (main ? 132 : 119);
    photograph(ctx, item, 14, 14, width - 28, imageHeight, background, main ? 18 : 12);
    caption(ctx, item, 23, imageHeight + 30, width - 46, { main, demo });
    tape(ctx, width / 2 - 59, -14, 118, main ? COLOR.yellow : COLOR.blue, main ? -.03 : .04);
    ctx.restore();
  }

  function validSources(item, records) {
    return Array.isArray(item?.source_ids) && item.source_ids.length > 0 &&
      item.source_ids.every(id => typeof id === 'string' && records.has(id));
  }

  function sourceDates(item, records) {
    return [...new Set(item.source_ids.map(id => date(records.get(id)?.date)).filter(Boolean))]
      .sort().map(value => value.replaceAll('-', '.'));
  }

  function finding(ctx, item, records, x, y, width, index) {
    roundedPaper(ctx, x, y, width, 199, index % 2 ? COLOR.blue : COLOR.sage, 16);
    const inset = 25;
    print(ctx, `0${index + 1}`, x + inset, y + 18, 40, { size: 15, maxLines: 1, weight: '600' });
    const heading = text(item.title) || '一条记录';
    print(ctx, heading, x + inset + 42, y + 15, width - inset * 2 - 42, {
      size: 26, lineHeight: 32, maxLines: 1, family: DISPLAY
    });
    print(ctx, shortObservation(item.text), x + inset, y + 61, width - inset * 2, {
      size: 19, lineHeight: 29, maxLines: 3
    });
    const dates = sourceDates(item, records);
    const sourceLabel = dates.length > 1 ? `${dates[0]} — ${dates[dates.length - 1]}` : dates[0];
    if (sourceLabel) print(ctx, `记录依据 · ${sourceLabel}`, x + inset, y + 169, width - inset * 2, {
      size: 13, maxLines: 1, color: COLOR.ink
    });
  }

  async function createCanvas(D = {}) {
    const meta = D.meta || {}, story = D.story || {}, overview = story.overview || {};
    const recordList = (Array.isArray(D.records) ? D.records : []).filter(record => record && typeof record.id === 'string');
    const records = new Map(recordList.map(record => [record.id, record]));
    const demo = meta.synthetic_demo === true || (recordList.length > 0 && recordList.every(r => Array.isArray(r.images) && r.images.length > 0 && r.images.every(im => im?.origin === 'synthetic_demo')));
    const title = text(overview.headline) || text(meta.title) || '物件之间，生活慢慢成形';
    if (document.fonts) {
      await Promise.allSettled([
        document.fonts.load(`92px ${DISPLAY}`, title + '消费手账记录里的小发现'),
        document.fonts.load(`24px ${BODY}`, '消费手账记录范围'),
        document.fonts.load(`25px ${NOTE}`, '这一页收着几件小东西')
      ]);
      await document.fonts.ready;
    }
    const candidates = (Array.isArray(D.share_images) ? D.share_images : [])
      .filter(asset => ['object', 'photo', 'design', 'cover'].includes(asset?.kind));
    const loaded = (await Promise.all(candidates.slice(0, 4).map(loadImage))).filter(Boolean).slice(0, 3);
    const canvas = document.createElement('canvas');
    canvas.width = 1080;
    canvas.height = 1440;
    canvas.className = 'share-preview';
    canvas.setAttribute('aria-label', demo ? '消费手账分享图：虚构演示数据，不代表真实消费' : '消费手账分享图：已收录的图片、日期与观察');
    canvas.dataset.shareImageCount = String(loaded.length);
    canvas.dataset.syntheticDemo = String(demo);
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('当前浏览器无法创建分享图');
    ctx.textBaseline = 'top';
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.fillStyle = COLOR.paper;
    ctx.fillRect(0, 0, 1080, 1440);

    // A faint paper grain is drawn locally; no texture or image is fetched.
    ctx.fillStyle = '#273e4a0b';
    for (let i = 0; i < 640; i++) ctx.fillRect((i * 157 + 19) % 1080, (i * 281 + 43) % 1440, 1.4, 1.4);
    roundedPaper(ctx, 62, 50, 213, 54, COLOR.yellow, 27);
    print(ctx, '我的消费手账', 88, 62, 173, { size: 26, family: DISPLAY, maxLines: 1 });
    const actualStart = date(meta.actual_range?.start), actualEnd = date(meta.actual_range?.end);
    const actualRange = actualStart && actualEnd ? `${actualStart.replaceAll('-', '.')} — ${actualEnd.replaceAll('-', '.')}` : '实际范围尚未确认';
    print(ctx, demo ? '演示记录范围' : '实际收录范围', 664, 53, 352, { size: 14, maxLines: 1, color: COLOR.muted });
    print(ctx, actualRange, 664, 78, 352, { size: 18, maxLines: 1 });

    let titleSize = 136;
    for (; titleSize > 58; titleSize -= 2) {
      ctx.font = `400 ${titleSize}px ${DISPLAY}`;
      const lines = linesFor(ctx, title, 944);
      if (lines.length <= 3 && lines.length * titleSize * 1.18 <= 218) break;
    }
    print(ctx, title, 63, 143, 944, { size: titleSize, lineHeight: titleSize * 1.18,
      maxLines: Math.max(1, Math.floor(218 / (titleSize * 1.18))), family: DISPLAY });
    const observation = validSources(overview, records) ? shortObservation(overview.note || overview.text) : '';
    ctx.save();
    ctx.translate(71, 381);
    ctx.rotate(-.014);
    roundedPaper(ctx, 0, 0, 930, 112, '#f5d98f', 6, true);
    tape(ctx, 392, -14, 139, COLOR.sage, .03);
    print(ctx, observation || (demo ? '用演示素材，试着拼一页生活手账。' : '这一页，选自已经收录的记录。'), 28, 24, 874,
      { size: 23, lineHeight: 34, maxLines: 2 });
    ctx.restore();

    print(ctx, demo ? '演示物件 / 贴在这一页' : '几件小东西，收在这一页', 78, 512, 620,
      { size: 19, family: NOTE, maxLines: 1, color: COLOR.muted });
    if (loaded.length) {
      const hero = loaded.length > 1
        ? { x: 81, y: 579, width: 497, height: 507, angle: -.065 }
        : { x: 207, y: 570, width: 666, height: 530, angle: -.035 };
      photoCard(ctx, loaded[0], { ...hero, background: COLOR.sage, main: true, demo });
      if (loaded[1]) {
        photoCard(ctx, loaded[1], { x: 642, y: 551, width: 338, height: loaded[2] ? 278 : 491,
          angle: .065, background: COLOR.blue, demo });
      }
      if (loaded[2]) {
        photoCard(ctx, loaded[2], { x: 642, y: 859, width: 338, height: 254,
          angle: -.035, background: '#ead0c1', demo });
      }
    } else {
      roundedPaper(ctx, 77, 573, 926, 514, COLOR.white, 14, true);
      tape(ctx, 460, 560, 150, COLOR.blue, -.04);
      print(ctx, '留一点空白，\n给没有图片的记录。', 119, 665, 834,
        { size: 58, lineHeight: 85, maxLines: 2, family: DISPLAY });
      print(ctx, '本页没有可用的已收录图片。', 123, 898, 760,
        { size: 22, lineHeight: 34, maxLines: 2, color: COLOR.muted });
    }

    print(ctx, demo ? '演示记录里的小发现' : '记录里的小发现', 64, 1135, 952,
      { size: 25, family: DISPLAY, maxLines: 1 });
    const findings = (Array.isArray(story.findings) ? story.findings : [])
      .filter(item => validSources(item, records) && (text(item.title) || text(item.text))).slice(0, 2);
    if (findings.length) {
      findings.forEach((item, index) => finding(ctx, item, records, 64 + index * 488, 1180,
        findings.length === 1 ? 952 : 464, index));
    } else {
      roundedPaper(ctx, 64, 1180, 952, 199, COLOR.sage, 16);
      print(ctx, '先把这些小东西收好。', 92, 1205, 896,
        { size: 31, maxLines: 1, family: DISPLAY });
      print(ctx, demo ? '本页仅用于展示排版效果，不代表任何人的真实购买。' : '已收录的片段保留在完整手账中，可以按日期回看。', 92, 1264, 896,
        { size: 21, lineHeight: 31, maxLines: 2 });
    }
    const footer = demo ? '虚构演示 · 仅供设计预览，不代表真实消费' : '消费手账 · 仅反映已收录范围';
    print(ctx, footer, 64, 1400, 820, { size: 15, maxLines: 1, color: COLOR.muted });
    print(ctx, '留作小记', 917, 1396, 99,
      { size: 20, family: NOTE, maxLines: 1, color: COLOR.muted });
    return canvas;
  }

  window.JournalEditorialShare = Object.freeze({ createCanvas });
})();
