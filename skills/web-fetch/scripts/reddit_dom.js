// Evaluated by agent-browser; page content is data, never executable input.
(({ postId, action = null, mode = 'snapshot' }) => {
  const post = document.querySelector(`shreddit-post[id="${postId}"]`);
  const pageText = document.body?.innerText || '';
  const sample = `${document.title}\n${pageText}`;
  const gateChecks = [
    ['network_security', /blocked by network security/i],
    ['human_verification', /prove your humanity|verify you are human/i],
    ['rate_limit', /whoa there, pardner|too many requests/i],
    ['private_or_banned', /private community|community is private|community has been banned/i],
  ];
  let gateReason = /^\/(?:login|account\/login)\/?$/i.test(location.pathname) ? 'login_required' : null;
  if (!gateReason) {
    const matched = gateChecks.find(([, pattern]) => pattern.test(sample));
    if (matched) gateReason = matched[0];
  }
  const unavailable = !gateReason && /page not found|content is no longer available/i.test(sample);
  const blocked = Boolean(gateReason);
  if (mode === 'ready') return Boolean(post || blocked || unavailable);
  if (!post) {
    const snippet = (pageText || document.title || 'Reddit post not rendered')
      .trim().replace(/\s+/g, ' ').slice(0, 240);
    return { source_url: location.href, post: null, comments: [], actions: [],
      blocked, gate_reason: gateReason || (unavailable ? 'not_found' : null),
      unavailable, page_title: document.title || null, error: snippet };
  }
  const roots = [document];
  for (let i = 0; i < roots.length; i++) {
    for (const element of roots[i].querySelectorAll('*')) {
      if (element.shadowRoot) roots.push(element.shadowRoot);
    }
  }
  const all = (selector) => roots.flatMap(root => [...root.querySelectorAll(selector)]);
  const owner = (element, selector) => {
    while (element) {
      if (element.matches?.(selector)) return element;
      element = element.parentElement || element.getRootNode()?.host;
    }
    return null;
  };
  const visible = element => element.getClientRects().length > 0 &&
    getComputedStyle(element).visibility !== 'hidden' &&
    !owner(element, '[hidden], [aria-hidden="true"]');
  const candidates = [];
  const add = (element, kind, href = null) => {
    const label = (element.innerText || element.textContent ||
      element.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
    const comment = owner(element, 'shreddit-comment');
    const key = JSON.stringify([kind, comment?.getAttribute('thingid'), label, href]);
    if (!candidates.some(candidate => candidate.key === key)) {
      candidates.push({ key, kind, href, element });
    }
  };
  for (const details of all('shreddit-comment > details:not([open])')) {
    const summary = details.querySelector(':scope > summary');
    if (summary && visible(summary)) add(summary, 'expand_comment');
  }
  const more = /^(?:read more|(?:\d[\d,.]*\s+)?more\s+(?:replies|reply|comments|comment)|(?:view|load|show)\s+(?:\d[\d,.]*\s+)?(?:more\s+)?(?:replies|reply|comments|comment)|continue (?:this|the) thread)(?:\s*\(\d[\d,.]*\))?$/i;
  for (const element of all('button, a, [role="button"]')) {
    if (!visible(element) || element.disabled) continue;
    if (!owner(element, 'shreddit-comment, shreddit-comment-tree') &&
        owner(element, 'shreddit-post') !== post) continue;
    const label = (element.innerText || element.textContent ||
      element.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
    if (!more.test(label)) continue;
    const href = element.getAttribute('href');
    if (href) {
      const url = new URL(href, location.href);
      const match = url.pathname.match(/^\/(?:r\/[^/]+\/)?comments\/([a-z0-9]+)(?:\/|$)/i);
      if (url.protocol !== 'https:' || !['reddit.com', 'www.reddit.com', 'old.reddit.com', 'new.reddit.com', 'np.reddit.com', 'm.reddit.com'].includes(url.hostname) ||
          url.username || url.password || url.port || !match || `t3_${match[1].toLowerCase()}` !== postId) continue;
      url.hash = '';
      add(element, 'navigate', url.href);
    } else {
      add(element, /^read more$/i.test(label) ? 'read_more' : 'more_comments');
    }
  }
  if (action) {
    if (action.kind === 'scroll') {
      const tree = document.querySelector('shreddit-comment-tree');
      tree?.scrollIntoView({ block: 'end' });
    } else {
      const target = candidates.find(candidate => candidate.key === action.key);
      if (!target || target.kind === 'navigate') throw new Error('Expansion control changed');
      target.element.click();
    }
    // A slow or ineffective expansion is reported as partial by the controller.
    return new Promise(resolve => setTimeout(() => resolve({ acted: true }), 1500));
  }
  const links = element => element ? [...new Set([...element.querySelectorAll('a[href]')]
    .map(anchor => anchor.href).filter(href => /^https?:\/\//i.test(href)))] : [];
  const postBody = post.querySelector(`[id="${postId}-post-rtjson-content"]`) ||
    post.querySelector('[slot="text-body"]');
  const bodyText = element => element ? (element.innerText || element.textContent || '').trim() : null;
  const comments = [...document.querySelectorAll('shreddit-comment')]
    .filter(comment => comment.getAttribute('postid') === postId)
    .map(comment => {
      const id = comment.getAttribute('thingid');
      const body = [...comment.querySelectorAll('[slot="comment"]')]
        .find(element => element.closest('shreddit-comment') === comment);
      const parent = comment.getAttribute('parentid') ||
        comment.parentElement?.closest('shreddit-comment')?.getAttribute('thingid') ||
        (comment.getAttribute('depth') === '0' ? postId : null);
      return { id, parent_id: parent, author: comment.getAttribute('author'),
        created_at: comment.getAttribute('created'), score: comment.getAttribute('score'),
        body_text: bodyText(body), links: links(body),
        permalink: `https://www.reddit.com/comments/${postId.slice(3)}/comment/${id?.slice(3)}/` };
    });
  const count = post.getAttribute('comment-count');
  return { source_url: location.href, blocked: false, gate_reason: null, unavailable: false, error: null,
    post: { id: postId, title: post.getAttribute('post-title'),
      author: post.getAttribute('author'), subreddit: post.getAttribute('subreddit-prefixed-name'),
      created_at: post.getAttribute('created-timestamp'), score: post.getAttribute('score'),
      body_text: bodyText(postBody), links: links(postBody),
      content_url: post.getAttribute('content-href'),
      body_expanded: !candidates.some(candidate => candidate.kind === 'read_more' &&
        owner(candidate.element, 'shreddit-post') === post),
      reported_comment_count: /^\d+$/.test(count || '') ? Number(count) : null },
    comments, actions: candidates.map(({ element, ...candidate }) => candidate) };
})
