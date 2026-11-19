/* 端侧推荐引擎：在浏览器本地完成推理与差分隐私加噪，原始兴趣数据不出端 */
const OnDevice = (() => {
  // 拉普拉斯噪声逆 CDF 采样
  function laplace(epsilon, sensitivity = 1) {
    const u = Math.random() - 0.5;
    return -sensitivity / epsilon * Math.sign(u) * Math.log(1 - 2 * Math.abs(u));
  }

  // 本地推理：使用服务端下发的模型参数，兴趣与商品标签仅在本地计算
  function scoreLocal(interests, products, params) {
    const weights = params.tag_weights || {};
    const pop = params.popularity || {};
    return products.map(p => {
      const matched = (p.tags || []).filter(t => interests.includes(t));
      let score = matched.reduce((s, t) => s + (weights[t] || 1), 0);
      score += (pop[p.id] || 0) * 0.1;
      return { ...p, score: +score.toFixed(2), matched, engine: 'on-device' };
    }).filter(p => p.matched.length > 0).sort((a, b) => b.score - a.score);
  }

  // 差分隐私上报：对每个标签的真实兴趣 + 拉普拉斯噪声，只上报加噪计数
  function buildPrivateReport(interests, params) {
    const eps = (params.privacy && params.privacy.epsilon) || 1.0;
    const vocab = params.tag_vocab || [];
    const counts = {};
    for (const t of vocab) {
      const real = interests.includes(t) ? 1 : 0;
      counts[t] = Math.max(0, +(real + laplace(eps, 1)).toFixed(3));
    }
    return { tag_counts: counts, client_version: params.version, epsilon: eps };
  }

  // 对比服务端推荐与端侧推荐的重合度
  function compare(serverRecs, localRecs) {
    const s = new Set((serverRecs || []).map(r => r.id));
    const l = new Set((localRecs || []).map(r => r.id));
    const inter = [...s].filter(x => l.has(x));
    const union = new Set([...s, ...l]);
    return {
      overlap: inter.length,
      jaccard: union.size ? +(inter.length / union.size).toFixed(2) : 0,
      server: [...s], local: [...l],
    };
  }

  return { laplace, scoreLocal, buildPrivateReport, compare };
})();
