// Design-only fixtures: no real navigation, input update or authentication changes.
state.finalProbePage = await context.newPage();
state.finalProbeRequests = 0;
await state.finalProbePage.route('**/*', async route => {
  if (/^https?:/.test(route.request().url())) {
    state.finalProbeRequests++;
    await route.abort();
  } else await route.continue();
});
try {
  const results = await state.finalProbePage.evaluate(async () => {
    const cases = [];
    const check = (name, condition) => cases.push({name, pass: !!condition});
    const articleOrigin = 'https://blackline.my.site.com';
    const authPath = /^\/app\/blus-production_blacklinesalesforcecommunity_1\/[A-Za-z0-9]+\/sso\/saml$/;

    // Recognize a stable, successfully loaded known identity-entry screen only.
    const authEvidence = snapshot => snapshot.status === 200 && snapshot.stable &&
      snapshot.origin === 'https://us.auth.blackline.com' && authPath.test(snapshot.path) &&
      snapshot.identifierVisible && snapshot.identifierCount === 1 && snapshot.formMatches &&
      snapshot.articleCount === 0;
    // Whole-run failures take precedence; the skip exception applies to auth only.
    const classify = (statuses, snapshot, runFailure = false) => {
      if (runFailure || statuses.some(s => s === 400 || (s >= 410 && s <= 499))) return 'stop';
      if (statuses.some(s => s >= 401 && s <= 409)) return 'skip';
      if (authEvidence(snapshot)) return 'auth-stop';
      return 'not-confirmed';
    };
    const positive = {status: 200, stable: true, origin: 'https://us.auth.blackline.com',
      path: '/app/blus-production_blacklinesalesforcecommunity_1/DUMMY/sso/saml',
      identifierVisible: true, identifierCount: 1, formMatches: true, articleCount: 0};
    check('known-identifier-screen', classify([], positive) === 'auth-stop');
    for (let status = 400; status <= 499; status++) {
      check('http-' + status, classify([status], positive) === (status >= 401 && status <= 409 ? 'skip' : 'stop'));
    }
    check('fatal-http-overrides-skip', classify([401, 410], positive) === 'stop');
    check('log-failure-overrides-skip', classify([401], positive, true) === 'stop');
    for (const [name, change] of [
      ['hidden-identifier', {identifierVisible: false}], ['duplicate-identifier', {identifierCount: 2}],
      ['different-origin', {origin: articleOrigin}], ['different-app', {path: '/app/other/DUMMY/sso/saml'}],
      ['saml-transfer-only', {path: '/BlackLineCommunity/saml/authn-request.jsp'}],
      ['error-document', {status: 500}], ['unstable', {stable: false}],
      ['article-still-present', {articleCount: 1}], ['different-form', {formMatches: false}],
    ]) check(name, classify([], {...positive, ...change}) === 'not-confirmed');

    // Preserve all API-declared fields; DOM order and labels must match exactly.
    const fixture = document.createElement('section');
    document.body.append(fixture);
    const build = (fields, options = {}) => {
      fixture.replaceChildren();
      fields.forEach((field, index) => {
        const wrapper = document.createElement('div');
        const label = document.createElement('span'); label.dataset.label = '';
        label.textContent = options.wrongLabel && index === 0 ? 'Wrong' : field.label;
        const host = document.createElement('lightning-formatted-rich-text');
        const shadow = host.attachShadow({mode: options.closed && index === 0 ? 'closed' : 'open'});
        const span = document.createElement('span'); span.innerHTML = field.html;
        shadow.append(span); wrapper.append(label, host);
        if (options.hidden && index === 0) wrapper.hidden = true;
        fixture.append(wrapper);
      });
    };
    const validate = (fields, fieldSet = true, values = Object.fromEntries(fields.map(f => [f.name, f.html]))) => {
      if (!fieldSet || new Set(fields.map(f => f.name)).size !== fields.length) return false;
      if (Object.entries(values).some(([name, value]) => value && !fields.some(f => f.name === name))) return false;
      const wrappers = [...fixture.children];
      if (wrappers.length !== fields.length) return false;
      return fields.every((field, index) => {
        const wrapper = wrappers[index];
        const host = wrapper.querySelector('lightning-formatted-rich-text');
        const shadow = host?.shadowRoot;
        const value = shadow?.children.length === 1 && shadow.firstElementChild.localName === 'span'
          ? shadow.firstElementChild.innerHTML : undefined;
        const label = wrapper.querySelector('[data-label]')?.textContent;
        if (!field.label || label !== field.label || value === undefined || value !== field.html) return false;
        return !field.html || host.getClientRects().length > 0;
      });
    };
    const six = Array.from({length: 6}, (_, i) => ({name: 'Field' + i, label: 'Label ' + i, html: '<p>Value ' + i + '</p>'}));
    build(six); check('six-api-fields-no-four-field-limit', validate(six));
    const reordered = [...six].reverse(); build(reordered);
    check('declared-field-order-supported', validate(reordered));
    check('wrong-dom-order-rejected', !validate(six));
    build(six, {wrongLabel: true}); check('wrong-label-rejected', !validate(six));
    build(six, {hidden: true}); check('hidden-nonempty-rejected', !validate(six));
    build(six, {closed: true}); check('closed-shadow-rejected', !validate(six));
    build(six); fixture.lastElementChild.remove(); check('missing-field-rejected', !validate(six));
    build(six); fixture.firstElementChild.querySelector('lightning-formatted-rich-text').shadowRoot.append(document.createElement('span'));
    check('unknown-shadow-structure-rejected', !validate(six));
    build(six); check('non-fieldset-display-rejected', !validate(six, false));
    check('undeclared-nonempty-api-value-rejected', !validate(six, true, {UnknownField: '<p>not declared</p>'}));
    check('duplicate-api-field-rejected', !validate([six[0], six[0]]));
    // Unknown wrappers/attributes remain in the structural comparison, not flattened.
    const canonical = html => {const t = document.createElement('template'); t.innerHTML = html; return t.innerHTML;};
    check('unknown-wrapper-preserved', canonical('<custom-node>value</custom-node>') !== canonical('value'));
    check('unknown-attribute-preserved', canonical('<span data-meaning="a">value</span>') !== canonical('<span data-meaning="b">value</span>'));

    // A local decode has one shared deadline and always revokes its own blob URL.
    const decodeSvg = async (source, ms, factory = () => new Image()) => {
      const url = URL.createObjectURL(new Blob([source], {type: 'image/svg+xml'}));
      const image = factory(); let timer;
      try {
        image.src = url;
        await Promise.race([image.decode(), new Promise((_, reject) => {timer = setTimeout(() => reject(new Error('IMAGE_TIMEOUT')), ms);})]);
        if (!(image.naturalWidth > 0 && image.naturalHeight > 0)) throw new Error('IMAGE_INVALID');
        return true;
      } finally {clearTimeout(timer); image.src = ''; URL.revokeObjectURL(url);}
    };
    const shapes = ["<rect width=\"8\" height=\"6\" fill=\"red\"/>", "<defs><linearGradient id=\"g\"><stop offset=\"0\" stop-color=\"#abc\"/></linearGradient></defs><rect width=\"8\" height=\"6\" fill=\"url(#g)\"/>", "<defs><rect id=\"r\" width=\"2\" height=\"3\"/></defs><use href=\"#r\" x=\"1\"/>", "<path d=\"M0 0 L8 0 8 6 Z\" transform=\"translate(1,2) rotate(30)\"/>", "<path d=\"M0 0 A2 3 0 0 1 4 5\"/>", "<polygon points=\"0,0 8,0 4,6\" fill=\"#ff000080\"/>", "<g id=\"shapes\" opacity=\"0.5\" fill-opacity=\"0.8\" stroke-opacity=\"1\" fill-rule=\"evenodd\" stroke=\"blue\" stroke-width=\"1px\" stroke-linecap=\"round\" stroke-linejoin=\"bevel\" stroke-miterlimit=\"2\" stroke-dasharray=\"1 2\" stroke-dashoffset=\"-1\"><circle cx=\"2\" cy=\"2\" r=\"1\"/><ellipse cx=\"4\" cy=\"2\" rx=\"1\" ry=\"2\"/><line x1=\"0\" y1=\"0\" x2=\"8\" y2=\"6\"/><polyline points=\"0 0 8 6\"/></g>", "<defs><radialGradient id=\"r\" cx=\"0.5\" cy=\"0.5\" r=\"0.5\" fx=\"0.2\" fy=\"0.2\" fr=\"0\" gradientUnits=\"objectBoundingBox\" spreadMethod=\"reflect\" gradientTransform=\"matrix(1 0 0 1 0 0)\"><stop offset=\"1\" stop-color=\"blue\" stop-opacity=\"0.5\"/></radialGradient></defs><rect width=\"8\" height=\"6\" fill=\"url(#r)\"/>", "<svg viewBox=\"0 0 8 6\" preserveAspectRatio=\"xMidYMid meet\"><title>Dummy</title><desc>Local only</desc><path d=\"M0 0h1v1c1 0 1 1 2 2s1 1 2 2q1 1 2 2t1 1z\" transform=\"scale(1,1) skewX(1) skewY(1)\"/></svg>", "<defs><linearGradient id=\"a\" href=\"#b\"/><linearGradient id=\"b\"><stop offset=\"0\" stop-color=\"red\"/></linearGradient></defs><rect width=\"8\" height=\"6\" fill=\"url(#a)\"/>", "<defs><rect id=\"r\" width=\"8\" height=\"6\"/></defs><use xmlns:xlink=\"http://www.w3.org/1999/xlink\" xlink:href=\"#r\"/>"];
    for (let i = 0; i < shapes.length; i++) {
      check('svg-decode-' + i, await decodeSvg('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="6">' + shapes[i] + '</svg>', 2000));
    }
    try {
      await decodeSvg('<svg/>', 20, () => ({decode: () => new Promise(() => {}), naturalWidth: 0, naturalHeight: 0}));
      check('svg-deadline-injected', false);
    } catch (error) {check('svg-deadline-injected', error.message === 'IMAGE_TIMEOUT');}
    fixture.remove();
    return {passed: cases.filter(c => c.pass).length, total: cases.length, failures: cases.filter(c => !c.pass)};
  });
  console.log({...results, externalHttpRequests: state.finalProbeRequests});
} finally {
  await state.finalProbePage.unroute('**/*');
  await state.finalProbePage.close();
  delete state.finalProbePage;
  delete state.finalProbeRequests;
}
