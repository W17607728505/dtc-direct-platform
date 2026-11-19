const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const S = {
  view: 'dash', users: [], products: [], campaigns: [], events: [], orders: [],
  stats: {}, channels: {}, recs: [], selectedUser: null, selectedProduct: null,
  lastResult: null, lastTargets: [],
  adapters: [], connections: [], fedStats: {}, fedActors: [], fedActivities: [],
  flParams: {}, flStats: {}, oauthStart: null, flReport: null, flAggResult: null,
  lastDelivery: null, fedResult: null,
  growth: {}, scorecard: null, templates: [], shareUrl: '', inviteCode: '',
};

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (!res.ok) {
    const e = await res.json().catch(() => ({ error: '请求失败' }));
    throw new Error(e.error || '请求失败');
  }
  return res.json();
}

let toastTimer = null;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 2600);
}

async function loadAll() {
  const [users, products, campaigns, events, orders, stats, meta,
    adapters, connections, fedStats, fedActors, fedActivities, flParams, flStats,
    growth, templates] = await Promise.all([
    api('/api/users'), api('/api/products'), api('/api/campaigns'),
    api('/api/events?limit=300'), api('/api/orders'), api('/api/stats'), api('/api/meta'),
    api('/api/adapters'), api('/api/oauth/connections'), api('/api/federation/stats'),
    api('/api/federation/actors'), api('/api/federation/activities'),
    api('/api/fl/params'), api('/api/fl/stats'), api('/api/growth'), api('/api/templates'),
  ]);
  S.users = users; S.products = products; S.campaigns = campaigns; S.events = events;
  S.orders = orders; S.stats = stats; S.channels = meta.channels;
  S.adapters = adapters; S.connections = connections; S.fedStats = fedStats;
  S.fedActors = fedActors; S.fedActivities = fedActivities;
  S.flParams = flParams; S.flStats = flStats; S.growth = growth; S.templates = templates;
  if (!S.selectedUser && users.length) S.selectedUser = users[0].did;
  if (!S.selectedProduct && products.length) S.selectedProduct = products[0].id;
}

async function loadRecs() {
  if (!S.selectedUser) { S.recs = []; return; }
  S.recs = await api('/api/recommendations?did=' + encodeURIComponent(S.selectedUser));
}

const chBadge = (ch) => {
  const c = S.channels[ch];
  if (!c) return '';
  return `<span class="badge ${c.real ? 'real' : 'sim'}">${c.real ? '真实' : '模拟'}</span>`;
};

/* ---------------- 视图 ---------------- */
function viewDash() {
  const s = S.stats;
  const kpis = [
    ['注册用户', s.users, '持有 DID 的用户'],
    ['在售商品', s.products, '商品目录'],
    ['累计触达', s.funnel.impression, '曝光次数'],
    ['成交订单', S.orders.length, '已完成支付'],
    ['GMV', '¥' + s.gmv, '累计成交金额', 'hl'],
    ['转化率', s.conversion_rate + '%', '曝光 → 成交'],
  ];
  const max = Math.max(1, s.funnel.impression);
  const funnel = [
    ['曝光', s.funnel.impression], ['点击', s.funnel.click], ['成交', s.funnel.purchase],
  ].map(([n, v]) => `<div class="funnel-row"><span class="fname">${n}</span><div class="funnel-bar">
      <div class="funnel-fill" style="width:${Math.max(4, v / max * 100)}%">${v}</div></div></div>`).join('');
  const cmax = Math.max(1, ...Object.values(s.by_channel));
  const channels = Object.keys(S.channels).map(ch => `<div class="bar-row"><span class="bl">${S.channels[ch].label}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${s.by_channel[ch] / cmax * 100}%"></div></div>
      <b>${s.by_channel[ch]}</b></div>`).join('');
  const events = (S.events.slice(0, 8)).map(e => `<tr>
      <td>${e.type === 'impression' ? '曝光' : e.type === 'click' ? '点击' : '成交'}</td>
      <td>${esc((S.users.find(u => u.did === e.did) || {}).name || e.did)}</td>
      <td>${esc((S.products.find(p => p.id === e.product_id) || {}).title || '-')}</td>
      <td>${esc((S.channels[e.channel] || {}).label || '-')}</td>
      <td class="did">${esc(e.ts)}</td></tr>`).join('');
  return `<div class="grid g6">${kpis.map(k => `<div class="kpi ${k[3] || ''}">
      <div class="label">${k[0]}</div><div class="value">${k[1]}</div><div class="foot">${k[2]}</div></div>`).join('')}</div>
    <div class="grid g2" style="margin-top:18px">
      <div class="card"><h3>触达转化漏斗</h3><p class="sub">曝光 → 点击 → 成交</p>${funnel}
        <p class="hint">点击率 ${s.click_rate}% · 转化率 ${s.conversion_rate}%</p></div>
      <div class="card"><h3>通道触达分布</h3><p class="sub">各通道累计曝光量</p>${channels}</div>
    </div>
    <div class="section-title">最近事件</div>
    <div class="card"><table><thead><tr><th>事件</th><th>用户</th><th>商品</th><th>通道</th><th>时间</th></tr></thead>
      <tbody>${events || '<tr><td colspan="5" class="empty">暂无事件</td></tr>'}</tbody></table></div>`;
}

function viewUsers() {
  const cards = S.users.map(u => {
    const consents = ['inbox', 'email', 'webpush'].map(ch => {
      const c = (u.consents && u.consents[ch]) || {};
      return `<div class="consent-item">
        <div class="consent-top"><b>${S.channels[ch] ? S.channels[ch].label : ch}</b>
          <label class="switch"><input type="checkbox" data-act="toggle-consent" data-did="${esc(u.did)}" data-ch="${ch}" ${c.enabled ? 'checked' : ''}>
          <span class="slider"></span></label></div>
        <div class="hint">每周上限
          <input type="number" min="1" max="20" value="${c.max_per_week || 3}" data-act="set-cap" data-did="${esc(u.did)}" data-ch="${ch}"></div>
        <div style="margin-top:6px">${chBadge(ch)}</div>
      </div>`;
    }).join('');
    return `<div class="user-card">
      <div class="user-head"><div><span class="avatar">${esc(u.name.slice(0, 1))}</span><span class="user-name">${esc(u.name)}</span></div>
        <button class="btn sm" data-act="view-recs" data-did="${esc(u.did)}">查看推荐</button></div>
      <div class="did">${esc(u.did)}</div>
      <label class="field">兴趣标签（逗号分隔）</label>
      <input value="${esc((u.interests || []).join(', '))}" data-act="edit-interests" data-did="${esc(u.did)}" placeholder="AI, 效率工具, 阅读">
      <div class="consent-grid">${consents}</div>
    </div>`;
  }).join('');
  return `<div class="card"><h3>新增用户</h3><p class="sub">创建持有 DID 的用户并声明兴趣；授权通道默认仅开启站内触达</p>
      <form data-form="user"><div class="grid g2">
        <div><label class="field">用户名称</label><input name="name" required placeholder="例如：小李"></div>
        <div><label class="field">兴趣标签（逗号分隔）</label><input name="interests" placeholder="AI, 设计, 阅读"></div>
      </div><div class="form-actions"><button class="btn primary" type="submit">创建用户</button></div></form></div>
    <div class="section-title">用户与同意账本 <span class="badge ok">合规核心</span></div>
    <div class="grid g2">${cards}</div>`;
}

function viewProducts() {
  const rows = S.products.map(p => `<tr>
      <td><b>${esc(p.title)}</b><br><span class="hint">${esc(p.desc)}</span></td>
      <td>¥${p.price}</td><td>${(p.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('')}</td>
      <td>${esc(p.owner)}</td><td class="did">${esc(p.created_at)}</td></tr>`).join('');
  return `<div class="card"><h3>发布商品</h3><p class="sub">商品进入统一目录，作为多通道分发的单一事实源</p>
      <form data-form="product">
        <div class="grid g2">
          <div><label class="field">商品标题</label><input name="title" required placeholder="例如：AI 写作助手"></div>
          <div><label class="field">价格（元）</label><input name="price" type="number" min="0" step="0.01" value="0"></div>
        </div>
        <label class="field">简介</label><textarea name="desc" placeholder="一句话介绍产品价值"></textarea>
        <div class="grid g2">
          <div><label class="field">标签（逗号分隔，用于兴趣匹配）</label><input name="tags" placeholder="AI, 效率工具"></div>
          <div><label class="field">创作者</label><input name="owner" placeholder="创作者名称"></div>
        </div>
        <div class="form-actions"><button class="btn primary" type="submit">发布商品</button></div>
      </form></div>
    <div class="section-title">商品目录</div>
    <div class="card"><table><thead><tr><th>商品</th><th>价格</th><th>标签</th><th>创作者</th><th>发布时间</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5" class="empty">暂无商品</td></tr>'}</tbody></table></div>`;
}

function viewReach() {
  const userOpts = S.users.map(u => `<option value="${esc(u.did)}" ${u.did === S.selectedUser ? 'selected' : ''}>${esc(u.name)} · ${esc(u.did)}</option>`).join('');
  const prodOpts = S.products.map(p => `<option value="${esc(p.id)}" ${p.id === S.selectedProduct ? 'selected' : ''}>${esc(p.title)}</option>`).join('');
  const chRadios = Object.keys(S.channels).map(ch => `<label style="display:flex;align-items:center;gap:8px;padding:8px 0;cursor:pointer">
      <input type="radio" name="channel" value="${ch}" ${ch === 'inbox' ? 'checked' : ''} style="width:auto">
      <b>${S.channels[ch].label}</b>${chBadge(ch)}<span class="hint">${S.channels[ch].desc}</span></label>`).join('');
  const recs = S.recs.map(r => `<div class="rec-item">
      <div><div class="rc-title">${esc(r.title)}</div>
        <div class="rc-meta">匹配标签：${(r.matched || []).map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div></div>
      <div style="display:flex;align-items:center;gap:8px"><span class="score">${r.score}</span>
        <button class="btn sm" data-act="pick-reach" data-pid="${esc(r.id)}">分发</button></div></div>`).join('');
  let result = '';
  if (S.lastResult) {
    const r = S.lastResult;
    const targets = S.lastTargets.map(t => `<tr><td>${esc(t.name)}</td><td>${esc(t.product)}</td>
        <td><button class="btn sm ok" data-act="sim-click" data-cid="${esc(t.campaign_id)}" data-did="${esc(t.did)}" data-pid="${esc(t.product_id)}" data-ch="${esc(t.channel)}">模拟点击</button>
        <button class="btn sm primary" data-act="sim-purchase" data-cid="${esc(t.campaign_id)}" data-did="${esc(t.did)}" data-pid="${esc(t.product_id)}" data-ch="${esc(t.channel)}">模拟成交</button></td></tr>`).join('');
    result = `<div class="result-box"><h3>分发结果 · ${esc(r.channel.label)}</h3>
      <div class="result-nums">
        <div><b class="badge ok">${r.sent}</b><span>成功触达</span></div>
        <div><b>${r.skipped.no_consent}</b><span>未授权跳过</span></div>
        <div><b>${r.skipped.no_match}</b><span>兴趣不匹配</span></div>
        <div><b>${r.skipped.freq_cap}</b><span>频次超限</span></div>
      </div>
      <p class="hint">合规拦截：无授权不发送、兴趣不匹配不发送、超过每周频次上限不发送</p>
      <div style="margin-top:10px"><button class="btn sm" data-act="publish-template" data-cid="${esc(r.campaign.id)}" data-pid="${esc(r.campaign.product_id)}">发布为可复刻模板</button></div>
      ${targets ? `<table style="margin-top:10px"><thead><tr><th>触达用户</th><th>商品</th><th>模拟行为</th></tr></thead><tbody>${targets}</tbody></table>` : ''}
    </div>`;
  }
  return `<div class="grid g2">
    <div class="card"><h3>兴趣匹配推荐</h3><p class="sub">基于用户兴趣标签与商品标签的加权匹配</p>
      <label class="field">选择用户</label><select data-act="set-user">${userOpts}</select>
      <div style="margin-top:10px">${recs || '<div class="empty">该用户暂无匹配商品</div>'}</div></div>
    <div class="card"><h3>发起多通道分发</h3><p class="sub">仅向已授权、兴趣匹配且未超频的用户触达</p>
      <form data-form="campaign">
        <label class="field">分发商品</label><select name="product_id">${prodOpts || '<option value="">无商品</option>'}</select>
        <label class="field">触达通道</label>${chRadios}
        <div class="form-actions"><button class="btn primary" type="submit" ${!S.products.length ? 'disabled' : ''}>发起分发</button></div>
      </form>
      ${result}
    </div></div>`;
}

function viewTracking() {
  const s = S.stats;
  const max = Math.max(1, s.funnel.impression);
  const funnel = [['曝光', s.funnel.impression], ['点击', s.funnel.click], ['成交', s.funnel.purchase]]
    .map(([n, v]) => `<div class="funnel-row"><span class="fname">${n}</span><div class="funnel-bar">
      <div class="funnel-fill" style="width:${Math.max(4, v / max * 100)}%">${v}</div></div></div>`).join('');
  const rows = S.events.map(e => `<tr><td>${e.type === 'impression' ? '曝光' : e.type === 'click' ? '点击' : '成交'}</td>
      <td>${esc((S.users.find(u => u.did === e.did) || {}).name || e.did)}</td>
      <td>${esc((S.products.find(p => p.id === e.product_id) || {}).title || '-')}</td>
      <td>${esc((S.channels[e.channel] || {}).label || '-')}</td>
      <td class="did">${esc(e.campaign_id || '-')}</td><td class="did">${esc(e.ts)}</td></tr>`).join('');
  const camps = S.campaigns.map(c => `<tr><td class="did">${esc(c.id)}</td><td>${esc(c.name)}</td>
      <td>${esc((S.products.find(p => p.id === c.product_id) || {}).title || '-')}</td>
      <td>${esc((S.channels[c.channel] || {}).label || '-')}</td><td>${c.sent}</td><td class="did">${esc(c.created_at)}</td></tr>`).join('');
  return `<div class="card"><h3>全链路事件追踪</h3><p class="sub">曝光 → 点击 → 成交，按活动与通道归因</p>${funnel}</div>
    <div class="section-title">分发活动</div>
    <div class="card"><table><thead><tr><th>活动ID</th><th>名称</th><th>商品</th><th>通道</th><th>触达数</th><th>时间</th></tr></thead>
      <tbody>${camps || '<tr><td colspan="6" class="empty">暂无活动</td></tr>'}</tbody></table></div>
    <div class="section-title">事件流</div>
    <div class="card"><table><thead><tr><th>事件</th><th>用户</th><th>商品</th><th>通道</th><th>活动</th><th>时间</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="6" class="empty">暂无事件</td></tr>'}</tbody></table></div>`;
}

function viewRevenue() {
  const s = S.stats;
  const rows = S.orders.map(o => `<tr><td class="did">${esc(o.id)}</td>
      <td>${esc((S.users.find(u => u.did === o.did) || {}).name || o.did)}</td>
      <td>${esc((S.products.find(p => p.id === o.product_id) || {}).title || '-')}</td>
      <td>¥${o.amount}</td><td>${esc((S.channels[o.channel] || {}).label || '-')}</td>
      <td class="did">${esc(o.campaign_id || '-')}</td><td class="did">${esc(o.ts)}</td></tr>`).join('');
  return `<div class="grid g3">
      <div class="kpi hl"><div class="label">累计 GMV</div><div class="value">¥${s.gmv}</div><div class="foot">成交总额</div></div>
      <div class="kpi"><div class="label">创作者分账 (90%)</div><div class="value">¥${s.creator_payout}</div><div class="foot">按成交透明结算</div></div>
      <div class="kpi"><div class="label">平台服务费 (10%)</div><div class="value">¥${s.platform_fee}</div><div class="foot">MVP 演示费率</div></div>
    </div>
    <div class="section-title">成交订单</div>
    <div class="card"><table><thead><tr><th>订单ID</th><th>用户</th><th>商品</th><th>金额</th><th>通道</th><th>归因活动</th><th>时间</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="7" class="empty">暂无订单，去「精准触达」模拟一笔成交</td></tr>'}</tbody></table></div>`;
}

function viewIntegrations() {
  const userOpts = S.users.map(u => `<option value="${esc(u.did)}" ${u.did === S.selectedUser ? 'selected' : ''}>${esc(u.name)}</option>`).join('');
  const cards = S.adapters.map(a => `<div class="adapter-card">
    <div class="adapter-head"><b>${esc(a.label)}</b>
      <span class="badge ${a.real_capable ? 'ok' : 'sim'}">${a.real_capable ? '可真实接入' : '仅模拟'}</span></div>
    <div class="kv">运行模式：${a.sandbox ? '<span class="badge warn">沙箱模拟</span>' : '<span class="badge ok">真实凭证已配置</span>'}</div>
    <div class="kv">最小 Scope：${a.scopes.map(s => `<span class="scope">${esc(s)}</span>`).join('')}</div>
    <div class="kv">速率限制：${a.rate_limit.minute}/分钟 · ${a.rate_limit.day}/天</div>
    <div class="kv">平台约束：${esc(a.constraint)}</div>
    <div class="kv">数据边界：${esc(a.data_boundary)}</div>
    <div style="margin-top:10px"><button class="btn sm primary" data-act="start-oauth" data-key="${esc(a.key)}">发起 OAuth 授权</button></div>
  </div>`).join('');
  const connRows = S.connections.map(c => `<tr>
    <td>${esc((S.adapters.find(a => a.key === c.adapter) || {}).label || c.adapter)}</td>
    <td>${esc((S.users.find(u => u.did === c.did) || {}).name || c.did)}</td>
    <td class="did">${esc(c.token_masked)}</td>
    <td>${c.sandbox ? '<span class="badge warn">沙箱</span>' : '<span class="badge ok">真实</span>'}</td>
    <td class="did">${esc(c.expires_at)}</td>
    <td><button class="btn sm ok" data-act="test-deliver" data-key="${esc(c.adapter)}" data-did="${esc(c.did)}">测试投递</button>
        <button class="btn sm" data-act="revoke-oauth" data-key="${esc(c.adapter)}" data-did="${esc(c.did)}">撤销</button></td></tr>`).join('');
  let oauthBox = '';
  if (S.oauthStart) {
    const o = S.oauthStart;
    oauthBox = `<div class="result-box"><h3>OAuth 授权 · ${esc(o.adapter.label)}</h3>
      <div class="oauth-url">${esc(o.authorize_url)}</div>
      <p class="hint">state = ${esc(o.state)}（防 CSRF，一次性）。生产环境跳转该 URL 完成平台授权后由重定向地址回调。</p>
      <form data-form="oauth-callback"><input type="hidden" name="state" value="${esc(o.state)}">
        <input type="hidden" name="key" value="${esc(o.adapter.key)}">
        <div class="grid g2">
          <div><label class="field">授权码 code（沙箱可任意填写）</label><input name="code" required placeholder="demo-code"></div>
          <div style="display:flex;align-items:end"><button class="btn primary" type="submit">完成授权</button></div>
        </div></form></div>`;
  }
  let deliverBox = '';
  if (S.lastDelivery) {
    deliverBox = `<div class="result-box"><h3>最近一次投递结果</h3>
      <pre style="font-size:11px;white-space:pre-wrap;margin:0">${esc(JSON.stringify(S.lastDelivery, null, 2))}</pre></div>`;
  }
  return `<div class="card"><h3>授权主体</h3><p class="sub">选择由哪个用户发起平台授权；令牌混淆存储，可随时撤销</p>
      <select data-act="set-user">${userOpts}</select></div>
    <div class="section-title">社媒通道适配器</div>
    <div class="grid g2">${cards}</div>
    ${oauthBox}
    <div class="section-title">已授权连接</div>
    <div class="card"><table><thead><tr><th>通道</th><th>用户</th><th>令牌</th><th>模式</th><th>过期时间</th><th>操作</th></tr></thead>
      <tbody>${connRows || '<tr><td colspan="6" class="empty">暂无连接，先在上方发起 OAuth 授权</td></tr>'}</tbody></table></div>
    ${deliverBox}
    <div class="privacy-note"><b>合规要点</b>：仅申请最小 Scope；用户须先与平台账号建立关系；速率限制由适配器强制执行；
      不抓取平台数据、不跨平台合并身份、不外传用户数据。设置 DTC_TELEGRAM_TOKEN / DTC_WECHAT_APPID / DTC_META_APPID /
      DTC_X_CLIENT_ID 环境变量即可切换为对应平台的真实 API 模式（真实调用代码已内置）。</div>`;
}

function viewFederation() {
  const f = S.fedStats;
  const types = f.activity_types || {};
  const metrics = [
    ['Actors', f.actors], ['有效关注', f.follows], ['活动数', f.activities],
    ['收件箱条目', f.inbox_items], ['Create', types.Create || 0], ['Accept', types.Accept || 0],
  ];
  const actorName = (url) => {
    try {
      const did = decodeURIComponent((url || '').split('/ap/actor/')[1] || '');
      return (S.users.find(u => u.did === did) || {}).name || did;
    } catch (e) { return url || '-'; }
  };
  const actors = S.fedActors.map(a => `<div class="actor-line"><b>${esc(a.name)}</b>
    <span class="did">${esc(a.id)}</span></div>`).join('');
  const acts = S.fedActivities.slice(0, 14).map(a => `<tr>
    <td><span class="badge ${a.type === 'Create' ? 'ok' : ''}">${esc(a.type)}</span></td>
    <td>${esc(actorName(a.actor))}</td>
    <td>${esc((a.object && a.object.name) || '-')}</td>
    <td class="did">${esc(a.published)}</td></tr>`).join('');
  const userOpts = S.users.map(u => `<option value="${esc(u.did)}">${esc(u.name)}</option>`).join('');
  const prodOpts = S.products.map(p => `<option value="${esc(p.id)}">${esc(p.title)}</option>`).join('');
  let res = '';
  if (S.fedResult) {
    res = `<div class="result-box"><h3>联邦操作结果</h3>
      <pre style="font-size:11px;white-space:pre-wrap;margin:0">${esc(JSON.stringify(S.fedResult, null, 2))}</pre></div>`;
  }
  return `<div class="grid g6">${metrics.map(m => `<div class="kpi fed-stat">
      <div class="value">${m[1]}</div><div class="label">${m[0]}</div></div>`).join('')}</div>
    <div class="grid g2" style="margin-top:18px">
      <div class="card"><h3>关注 / 取消关注</h3><p class="sub">用户关注创作者 Actor，构建去中心化的订阅关系</p>
        <form data-form="fed-follow">
          <label class="field">关注者</label><select name="follower">${userOpts}</select>
          <label class="field">被关注创作者</label><select name="target">${userOpts}</select>
          <div class="form-actions"><button class="btn primary" type="submit">建立关注</button></div>
        </form>
        <form data-form="fed-unfollow" style="margin-top:12px">
          <label class="field">取消关注（关注者 → 创作者）</label>
          <div class="grid g2">
            <select name="follower">${userOpts}</select><select name="target">${userOpts}</select>
          </div>
          <div class="form-actions"><button class="btn" type="submit">取消关注</button></div>
        </form></div>
      <div class="card"><h3>商品联邦广播</h3><p class="sub">商品发布作为 Create 活动投递到所有关注者的 inbox</p>
        <form data-form="fed-announce">
          <label class="field">发布者 Actor</label><select name="actor">${userOpts}</select>
          <label class="field">商品</label><select name="product_id">${prodOpts || '<option value="">无商品</option>'}</select>
          <div class="form-actions"><button class="btn primary" type="submit" ${!S.products.length ? 'disabled' : ''}>广播到联邦网络</button></div>
        </form>
        <div class="section-title">Actor 列表</div>${actors}</div>
    </div>
    <div class="section-title">联邦活动流（Outbox / Inbox）</div>
    <div class="card"><table><thead><tr><th>活动类型</th><th>发起者</th><th>对象</th><th>时间</th></tr></thead>
      <tbody>${acts || '<tr><td colspan="4" class="empty">暂无活动</td></tr>'}</tbody></table></div>
    ${res}
    <div class="privacy-note"><b>协议说明</b>：实现 ActivityPub 风格端点 —— WebFinger（<code>/.well-known/webfinger</code>）、
      Actor 文档、inbox/outbox/followers 集合。Follow 自动回 Accept；商品发布生成 Create 活动并投递到关注者收件箱。
      触达由用户订阅关系驱动，不依赖任何社媒中介；联邦投递接口可直接对接远程实例。</div>`;
}

function viewOnDevice() {
  const p = S.flParams, st = S.flStats;
  const user = S.users.find(u => u.did === S.selectedUser);
  let localRecs = [], privateCounts = null, cmp = null;
  if (user && p.tag_vocab) {
    localRecs = OnDevice.scoreLocal(user.interests || [], S.products, p);
    privateCounts = Object.entries(OnDevice.buildPrivateReport(user.interests || [], p).tag_counts)
      .slice(0, 8);
    cmp = OnDevice.compare(S.recs, localRecs);
  }
  const srvRows = (S.recs || []).map(r => `<div class="compare-item"><span>${esc(r.title)}</span><b class="score">${r.score}</b></div>`).join('');
  const locRows = localRecs.map(r => `<div class="compare-item"><span>${esc(r.title)}</span><b class="score">${r.score}</b></div>`).join('');
  const weights = Object.entries(p.tag_weights || {}).map(([t, w]) => `<span class="tag">${esc(t)}: ${w}</span>`).join('');
  let reportBox = '';
  if (S.flReport) {
    reportBox = `<div class="result-box"><h3>端侧上报内容（本地已加噪）</h3>
      <p class="hint">服务端只收到以下聚合统计，看不到原始兴趣标签或个人行为</p>
      <pre style="font-size:11px;white-space:pre-wrap;margin:0">${esc(JSON.stringify(S.flReport, null, 2))}</pre></div>`;
  }
  let aggBox = '';
  if (S.flAggResult) {
    aggBox = `<div class="result-box"><h3>FedAvg 聚合结果</h3>
      <pre style="font-size:11px;white-space:pre-wrap;margin:0">${esc(JSON.stringify(S.flAggResult, null, 2))}</pre></div>`;
  }
  const userOpts = S.users.map(u => `<option value="${esc(u.did)}" ${u.did === S.selectedUser ? 'selected' : ''}>${esc(u.name)}</option>`).join('');
  return `<div class="grid g3">
      <div class="kpi"><div class="label">模型版本</div><div class="value">v${st.version}</div><div class="foot">全局标签权重版本</div></div>
      <div class="kpi"><div class="label">联邦轮次</div><div class="value">${st.rounds}</div><div class="foot">已完成 FedAvg 聚合次数</div></div>
      <div class="kpi hl"><div class="label">待聚合更新</div><div class="value">${st.pending_updates}</div><div class="foot">端侧加噪上报数</div></div>
    </div>
    <div class="card" style="margin-top:18px"><h3>推理主体</h3><p class="sub">选择用户，浏览器本地加载模型参数并计算推荐，原始兴趣不出端</p>
      <select data-act="set-user">${userOpts}</select>
      <div class="kv" style="margin-top:12px">当前标签权重（服务端下发）：${weights || '-'}</div>
      <div class="kv">隐私机制：ε = ${esc(st.epsilon)} · ${esc(st.privacy)}</div></div>
    <div class="section-title">服务端推荐 vs 端侧推荐</div>
    <div class="compare">
      <div class="compare-col"><h4>服务端推荐（兴趣上传）</h4>${srvRows || '<div class="empty">无匹配</div>'}</div>
      <div class="compare-col ondevice"><h4>端侧推荐（数据不出端）</h4>${locRows || '<div class="empty">无匹配</div>'}</div>
    </div>
    ${cmp ? `<p class="hint">Top 重合 ${cmp.overlap} 项 · Jaccard 相似度 ${cmp.jaccard} · 端侧推理结果与服务端接近，但隐私泄露面为零</p>` : ''}
    <div class="section-title">联邦学习闭环</div>
    <div class="grid g2">
      <div class="card"><h3>1. 端侧差分隐私上报</h3><p class="sub">对真实兴趣加拉普拉斯噪声，只上报标签计数</p>
        <div>${(privateCounts || []).map(([t, c]) => `<div class="compare-item"><span>${esc(t)}</span><b>${c}</b></div>`).join('')}</div>
        <div class="form-actions"><button class="btn primary" data-act="fl-report">上报加噪统计</button></div></div>
      <div class="card"><h3>2. 服务端 FedAvg 聚合</h3><p class="sub">聚合多端加噪更新，更新全局标签权重，不接触个人数据</p>
        <div class="kv">当前版本 v${st.version} · 轮次 ${st.rounds} · 待聚合 ${st.pending_updates}</div>
        <div class="form-actions"><button class="btn ok" data-act="fl-aggregate" ${st.pending_updates ? '' : 'disabled'}>执行聚合</button></div></div>
    </div>
    ${reportBox}${aggBox}
    <div class="privacy-note"><b>隐私保障</b>：端侧使用本地模型参数推理；上报值 = 真实兴趣 + Laplace(ε) 噪声，且只上报聚合计数；
      服务端存储的是 DID 哈希而非明文身份；FedAvg 只更新全局标签权重，无法实现个体反推。</div>`;
}

function viewGrowth() {
  const g = S.growth;
  const f = g.funnel || {};
  const steps = [
    ['分享成绩单', f.share_created || 0], ['邀请访问', f.invite_visit || 0],
    ['完成核心体验', f.invite_convert || 0], ['模板复刻', f.template_clone || 0],
  ];
  const max = Math.max(1, ...steps.map(s => s[1]));
  const bars = steps.map(s => `<div class="funnel-row"><span class="fname">${s[0]}</span>
    <div class="funnel-bar"><div class="funnel-fill" style="width:${Math.max(4, s[1] / max * 100)}%">${s[1]}</div></div></div>`).join('');
  const tpls = S.templates.slice(0, 6).map(t => `<tr><td><span class="badge ok">${esc(t.code)}</span>
    <div class="hint" style="max-width:200px;word-break:break-all">${esc(location.origin + '/?template=' + t.code)}</div></td>
    <td>${esc(t.name)}</td><td>${esc((S.products.find(p => p.id === t.product_id) || {}).title || '-')}</td>
    <td>${t.clones}</td><td><button class="btn sm primary" data-act="clone-template" data-code="${esc(t.code)}">一键复刻</button>
    <button class="btn sm" data-act="copy-template" data-code="${esc(t.code)}">复制链接</button></td></tr>`).join('');
  const shares = (g.top_shares || []).map(s => `<tr><td><span class="badge ok">${esc(s.code)}</span></td>
    <td>${esc(s.card.headline)}</td><td>${s.views}</td><td>${s.conversions}</td></tr>`).join('');
  const evs = (g.recent_events || []).map(e => `<tr><td><span class="badge ${e.type === 'invite_convert' ? 'ok' : ''}">${esc(e.type)}</span></td>
    <td class="did">${esc(e.code || '-')}</td><td class="did">${esc(e.ts)}</td></tr>`).join('');
  let cardBox = '';
  if (S.scorecard) {
    const c = S.scorecard.card;
    cardBox = `<div class="scorecard" id="scorecardCard">
      <div class="sc-label">DTC 直达 · 触达成单卡</div>
      <div class="sc-headline">${esc(c.headline)}</div>
      <div class="sc-owner">${esc(c.owner)} · 不依赖平台中介</div>
      <div class="sc-grid">
        <div><b>${c.touch}</b><span>直达触达</span></div>
        <div><b>${c.conversion_rate}%</b><span>成交转化率</span></div>
        <div><b>¥${c.creator_payout}</b><span>创作者分账</span></div>
        <div><b>${c.fed_follows}</b><span>联邦订阅者</span></div>
      </div>
      <div class="sc-foot">${esc(c.compliant_note)}</div>
      <div class="sc-code">专属邀请码 <b>${esc(S.scorecard.code)}</b></div>
    </div>
    <div class="result-box"><h3>分享链接</h3>
      <div class="oauth-url">${esc(S.scorecard.url)}</div>
      <button class="btn primary" data-act="copy-share">复制分享链接</button>
      <button class="btn" data-act="download-scorecard">保存卡片为图片</button></div>`;
  }
  return `<div class="grid g3">
      <div class="kpi hl"><div class="label">病毒系数 K</div><div class="value">${g.k_factor}</div>
        <div class="foot">${esc(g.formula)}</div></div>
      <div class="kpi"><div class="label">人均分享 i</div><div class="value">${g.invites_per_user}</div><div class="foot">每位用户分享次数</div></div>
      <div class="kpi"><div class="label">访问转化 c</div><div class="value">${g.visit_to_convert}</div><div class="foot">访问→核心体验完成率</div></div>
    </div>
    <div class="grid g2" style="margin-top:18px">
      <div class="card"><h3>传播漏斗</h3><p class="sub">分享 → 访问 → 体验 → 复刻</p>${bars}
        <p class="hint">累计分享浏览 ${g.total_share_views} · 累计转化 ${g.total_conversions} · 模板复刻 ${g.total_clones}</p></div>
      <div class="card"><h3>生成我的成绩单</h3><p class="sub">用真实触达成效生成可分享卡片，系统自动带专属邀请码</p>
        <label class="field">选择用户</label>
        <select data-act="set-user">${S.users.map(u => `<option value="${esc(u.did)}" ${u.did === S.selectedUser ? 'selected' : ''}>${esc(u.name)}</option>`).join('')}</select>
        <label class="field">关联触达活动（可选）</label>
        <select id="scorecardCampaign"><option value="">全局数据</option>
          ${S.campaigns.map(c => `<option value="${esc(c.id)}">${esc(c.name)} · 触达 ${c.sent}</option>`).join('')}</select>
        <div class="form-actions"><button class="btn primary" data-act="gen-scorecard">生成成绩单卡片</button></div>
      </div>
    </div>
    ${cardBox}
    <div class="section-title">排行榜 · 成绩单</div>
    <div class="card"><table><thead><tr><th>邀请码</th><th>标题</th><th>浏览</th><th>转化</th></tr></thead>
      <tbody>${shares || '<tr><td colspan="4" class="empty">暂无分享，生成一个成绩单</td></tr>'}</tbody></table></div>
    <div class="section-title">活动模板 · 一键复刻</div>
    <div class="card"><table><thead><tr><th>模板码</th><th>名称</th><th>商品</th><th>被复刻</th><th>操作</th></tr></thead>
      <tbody>${tpls || '<tr><td colspan="5" class="empty">暂无模板</td></tr>'}</tbody></table></div>
    <div class="section-title">邀请来源事件流</div>
    <div class="card"><table><thead><tr><th>事件</th><th>邀请码</th><th>时间</th></tr></thead>
      <tbody>${evs || '<tr><td colspan="3" class="empty">暂无邀请事件</td></tr>'}</tbody></table></div>`;
}

const VIEWS = {
  dash: { title: '总览', sub: '平台核心指标与触达漏斗', render: viewDash },
  users: { title: '用户与授权', sub: 'DID 身份、兴趣标签与同意账本', render: viewUsers },
  products: { title: '商品发布', sub: '统一商品目录，单一事实源', render: viewProducts },
  reach: { title: '精准触达', sub: '兴趣匹配、合规分发与闭环验证', render: viewReach },
  tracking: { title: '数据追踪', sub: '曝光到成交的全链路归因', render: viewTracking },
  revenue: { title: '变现订单', sub: 'GMV 与分账结算', render: viewRevenue },
  integrations: { title: '通道集成', sub: '社媒 OAuth 授权、适配器与合规约束', render: viewIntegrations },
  federation: { title: '联邦网络', sub: '基于开放协议的去中心化订阅触达', render: viewFederation },
  ondevice: { title: '端侧推荐', sub: '本地推理、差分隐私上报与联邦聚合', render: viewOnDevice },
  growth: { title: '增长实验', sub: '成绩单分享、邀请追踪与病毒系数验证', render: viewGrowth },
};

async function render() {
  const v = VIEWS[S.view];
  $('#pageTitle').textContent = v.title;
  $('#pageSub').textContent = v.sub;
  $('#view').innerHTML = v.render();
  document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === S.view));
}

/* ---------------- 事件 ---------------- */
document.addEventListener('click', async (e) => {
  const nav = e.target.closest('.nav-item');
  if (nav) { S.view = nav.dataset.view; await render(); return; }
  const btn = e.target.closest('[data-act]');
  if (!btn) return;
  const act = btn.dataset.act;
  try {
    if (act === 'publish-template') {
      const r = await api('/api/templates', { method: 'POST',
        body: JSON.stringify({ did: S.selectedUser, campaign_id: btn.dataset.cid,
          product_id: btn.dataset.pid }) });
      await loadAll(); await loadRecs();
      S.view = 'growth'; await render();
      toast('模板已发布，模板码 ' + r.code + ' · 可分享给好友一键复刻');
    } else if (act === 'gen-scorecard') {
      const camp = $('#scorecardCampaign').value || null;
      const r = await api('/api/share/scorecard', { method: 'POST',
        body: JSON.stringify({ did: S.selectedUser, campaign_id: camp }) });
      S.scorecard = { ...r, url: location.origin + '/?invite=' + r.code };
      S.inviteCode = r.code;
      await loadAll(); await render(); toast('成绩单已生成，邀请码 ' + r.code);
    } else if (act === 'copy-template') {
      await navigator.clipboard.writeText(location.origin + '/?template=' + btn.dataset.code);
      toast('模板复刻链接已复制');
    } else if (act === 'clone-template') {
      const r = await api('/api/templates/clone', { method: 'POST',
        body: JSON.stringify({ code: btn.dataset.code, did: S.selectedUser }) });
      S.lastResult = r; S.view = 'reach'; await loadAll(); await render();
      toast('模板已复刻：新增触达 ' + r.sent + ' 人');
    } else if (act === 'copy-share') {
      await navigator.clipboard.writeText(S.scorecard.url);
      toast('分享链接已复制');
    } else if (act === 'download-scorecard') {
      await downloadScorecard();
    } else if (act === 'start-oauth') {
      const r = await api('/api/oauth/start', { method: 'POST',
        body: JSON.stringify({ key: btn.dataset.key, did: S.selectedUser }) });
      S.oauthStart = r; await render(); toast('已生成授权请求，请完成授权');
    } else if (act === 'test-deliver') {
      const r = await api('/api/oauth/deliver', { method: 'POST',
        body: JSON.stringify({ did: btn.dataset.did, key: btn.dataset.key, text: 'DTC MVP 测试消息' }) });
      S.lastDelivery = r; await loadAll(); await render();
      toast(r.sandbox ? '沙箱投递成功（模拟）' : '真实投递成功');
    } else if (act === 'revoke-oauth') {
      await api('/api/oauth/revoke', { method: 'POST',
        body: JSON.stringify({ did: btn.dataset.did, key: btn.dataset.key }) });
      await loadAll(); await render(); toast('授权已撤销');
    } else if (act === 'fl-report') {
      const user = S.users.find(u => u.did === S.selectedUser);
      const report = OnDevice.buildPrivateReport(user.interests || [], S.flParams);
      const resp = await api('/api/fl/report', { method: 'POST',
        body: JSON.stringify({ ...report, did: S.selectedUser }) });
      S.flReport = { report, response: resp };
      await loadAll(); await render(); toast('加噪统计已上报，服务端无法还原原始兴趣');
    } else if (act === 'fl-aggregate') {
      const r = await api('/api/fl/aggregate', { method: 'POST', body: '{}' });
      S.flAggResult = r; await loadAll(); await render();
      toast(`FedAvg 完成，聚合 ${r.aggregated} 端，模型升级到 v${r.version}`);
    } else if (act === 'view-recs') {
      S.selectedUser = btn.dataset.did; await loadRecs(); S.view = 'reach'; await render();
    } else if (act === 'pick-reach') {
      S.selectedProduct = btn.dataset.pid;
      await render();
      document.querySelector('[data-form="campaign"] select[name="product_id"]').value = S.selectedProduct;
      toast('已选择商品，可发起分发');
    } else if (act === 'sim-click' || act === 'sim-purchase') {
      const payload = { did: btn.dataset.did, product_id: btn.dataset.pid,
        campaign_id: btn.dataset.cid, channel: btn.dataset.ch };
      if (act === 'sim-click') await api('/api/click', { method: 'POST', body: JSON.stringify(payload) });
      else await api('/api/purchase', { method: 'POST', body: JSON.stringify(payload) });
      await loadAll(); await render();
      if (act === 'sim-purchase') await recordConversion();
      toast(act === 'sim-click' ? '已记录点击事件' : '成交完成，订单与分账已生成');
    }
  } catch (err) { toast('操作失败：' + err.message); }
});

document.addEventListener('change', async (e) => {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  const act = el.dataset.act, did = el.dataset.did, ch = el.dataset.ch;
  try {
    if (act === 'set-user') {
      S.selectedUser = el.value; await loadRecs(); await render();
    } else if (act === 'toggle-consent' || act === 'set-cap') {
      const u = S.users.find(x => x.did === did);
      const c = (u.consents && u.consents[ch]) || {};
      await api('/api/users/' + encodeURIComponent(did) + '/consents', {
        method: 'PUT',
        body: JSON.stringify({ channel: ch, enabled: act === 'toggle-consent' ? el.checked : !!c.enabled,
          max_per_week: act === 'set-cap' ? Number(el.value) : (c.max_per_week || 3) }),
      });
      await loadAll(); await render(); toast('同意账本已更新');
    } else if (act === 'edit-interests') {
      const interests = el.value.split(/[,，]/).map(s => s.trim()).filter(Boolean);
      await api('/api/users/' + encodeURIComponent(did) + '/interests', {
        method: 'PUT', body: JSON.stringify({ interests }),
      });
      await loadAll(); await loadRecs(); await render(); toast('兴趣标签已更新，推荐已重算');
    }
  } catch (err) { toast('操作失败：' + err.message); }
});

document.addEventListener('submit', async (e) => {
  const form = e.target.closest('[data-form]');
  if (!form) return;
  e.preventDefault();
  const fd = new FormData(form);
  const data = Object.fromEntries(fd.entries());
  try {
    if (form.dataset.form === 'user') {
      data.interests = (data.interests || '').split(/[,，]/).map(s => s.trim()).filter(Boolean);
      const u = await api('/api/users', { method: 'POST', body: JSON.stringify(data) });
      await loadAll(); S.selectedUser = u.did; await loadRecs(); await render(); toast('用户已创建');
    } else if (form.dataset.form === 'product') {
      data.tags = (data.tags || '').split(/[,，]/).map(s => s.trim()).filter(Boolean);
      data.price = Number(data.price || 0);
      const p = await api('/api/products', { method: 'POST', body: JSON.stringify(data) });
      await loadAll(); S.selectedProduct = p.id; await render(); toast('商品已发布');
    } else if (form.dataset.form === 'campaign') {
      const r = await api('/api/campaigns', { method: 'POST', body: JSON.stringify(data) });
      S.lastResult = r;
      const imps = (await api('/api/events?limit=300')).filter(
        ev => ev.type === 'impression' && ev.campaign_id === r.campaign.id);
      S.lastTargets = imps.map(ev => ({
        did: ev.did, name: (S.users.find(u => u.did === ev.did) || {}).name || ev.did,
        product_id: ev.product_id, product: (S.products.find(p => p.id === ev.product_id) || {}).title || '-',
        campaign_id: r.campaign.id, channel: r.channel.id || ev.channel,
      }));
      S.events = imps.concat(S.events);
      await render(); toast('分发完成：成功触达 ' + r.sent + ' 人');
    } else if (form.dataset.form === 'oauth-callback') {
      await api('/api/oauth/callback', { method: 'POST', body: JSON.stringify(data) });
      S.oauthStart = null; await loadAll(); await render(); toast('授权成功，连接已建立');
    } else if (form.dataset.form === 'fed-follow') {
      const r = await api('/api/federation/follow', { method: 'POST', body: JSON.stringify(data) });
      S.fedResult = r; await loadAll(); await render(); toast('关注已建立，Accept 已回投');
    } else if (form.dataset.form === 'fed-unfollow') {
      const r = await api('/api/federation/unfollow', { method: 'POST', body: JSON.stringify(data) });
      S.fedResult = r; await loadAll(); await render(); toast('已取消关注');
    } else if (form.dataset.form === 'fed-announce') {
      const r = await api('/api/federation/announce', { method: 'POST', body: JSON.stringify(data) });
      S.fedResult = r; await loadAll(); await render(); toast(`商品已广播到 ${r.delivered} 个关注者`);
    }
  } catch (err) { toast('操作失败：' + err.message); }
});

$('#btnRefresh').addEventListener('click', async () => {
  await loadAll(); await loadRecs(); await render(); toast('数据已刷新');
});
$('#btnReset').addEventListener('click', async () => {
  await api('/api/reset', { method: 'POST', body: '{}' });
  S.selectedUser = null; S.selectedProduct = null; S.lastResult = null; S.lastTargets = [];
  S.oauthStart = null; S.flReport = null; S.flAggResult = null;
  S.lastDelivery = null; S.fedResult = null;
  await loadAll(); await loadRecs(); await render(); toast('已重置为演示数据');
});

async function downloadScorecard() {
  const c = S.scorecard.card;
  const canvas = document.createElement('canvas');
  canvas.width = 720; canvas.height = 440;
  const ctx = canvas.getContext('2d');
  const grad = ctx.createLinearGradient(0, 0, 720, 440);
  grad.addColorStop(0, '#232747'); grad.addColorStop(1, '#3a2f6b');
  ctx.fillStyle = grad; ctx.fillRect(0, 0, 720, 440);
  ctx.fillStyle = '#9aa0c8'; ctx.font = '18px sans-serif';
  ctx.fillText('DTC 直达 · 触达成单卡', 44, 58);
  ctx.fillStyle = '#ffffff'; ctx.font = 'bold 40px sans-serif';
  ctx.fillText(c.headline, 44, 122);
  ctx.fillStyle = '#b9bed6'; ctx.font = '18px sans-serif';
  ctx.fillText(c.owner + ' · 不依赖平台中介', 44, 158);
  const cells = [
    [String(c.touch), '直达触达'], [c.conversion_rate + '%', '成交转化率'],
    ['¥' + c.creator_payout, '创作者分账'], [String(c.fed_follows), '联邦订阅者'],
  ];
  cells.forEach((cell, i) => {
    const x = 44 + i * 165;
    ctx.fillStyle = 'rgba(255,255,255,0.08)';
    ctx.fillRect(x, 195, 150, 110);
    ctx.fillStyle = '#ffffff'; ctx.font = 'bold 28px sans-serif';
    ctx.fillText(cell[0], x + 14, 240);
    ctx.fillStyle = '#9aa0c8'; ctx.font = '15px sans-serif';
    ctx.fillText(cell[1], x + 14, 278);
  });
  ctx.fillStyle = '#8be0bd'; ctx.font = '15px sans-serif';
  ctx.fillText(c.compliant_note, 44, 350);
  ctx.fillStyle = '#ffffff'; ctx.font = 'bold 18px sans-serif';
  ctx.fillText('邀请码 ' + S.scorecard.code, 44, 400);
  const a = document.createElement('a');
  a.download = 'DTC-成绩单-' + S.scorecard.code + '.png';
  a.href = canvas.toDataURL('image/png');
  a.click();
  toast('成绩单卡片已保存');
}

async function trackInviteFromUrl() {
  const params = new URLSearchParams(location.search);
  const invite = params.get('invite');
  const template = params.get('template');
  const visitor = 'visitor_' + Math.random().toString(36).slice(2, 8);
  if (invite) {
    S.inviteCode = invite;
    try {
      const share = await api('/api/share/scorecard?code=' + encodeURIComponent(invite)
        + '&visitor=' + encodeURIComponent(visitor));
      S.scorecard = { code: share.code, url: location.origin + '/?invite=' + share.code, card: share.card };
      toast('你通过邀请码 ' + invite + ' 来访，来看看如何直达用户');
    } catch (e) { /* 邀请码无效则忽略 */ }
  }
  if (template) {
    try {
      const r = await api('/api/templates/clone', { method: 'POST',
        body: JSON.stringify({ code: template, did: null, visitor }) });
      S.lastResult = r; S.view = 'reach';
      toast('已通过模板 ' + template + ' 一键复刻，新增触达 ' + r.sent + ' 人');
    } catch (e) { toast('模板复刻失败：' + e.message); }
  }
  if (invite || template) {
    history.replaceState(null, '', location.pathname);
  }
}

async function recordConversion() {
  if (!S.inviteCode) return;
  try {
    await api('/api/invite/convert', { method: 'POST',
      body: JSON.stringify({ code: S.inviteCode, did: S.selectedUser }) });
    toast('邀请转化已记录，K 因子已更新');
  } catch (e) { /* 忽略埋点失败 */ }
}

(async function init() {
  await loadAll(); await loadRecs();
  await trackInviteFromUrl();
  await loadAll(); await loadRecs();
  await render();
})();
