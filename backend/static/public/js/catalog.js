/*
 * Course catalog (/courses/, public/courses.html): search, filters and sorting
 * in the browser, no page reloads. The server renders every published course
 * as a card in the «Рекомендуемые» order with data-* attributes (see the
 * template); this script hides, shows and reorders those cards.
 *
 * The state lives in the URL query (?q=&level=&access=&discount=1&sort=), kept
 * with history.replaceState and read on load, so a copied link or the Back
 * button from a course page shows the same selection. Defaults are left out
 * of the URL. Without JS the filters stay hidden and the page is the full list.
 */
(function () {
  'use strict';

  var root = document.querySelector('[data-catalog]');
  var form = root && root.querySelector('[data-catalog-filters]');
  if (!form) return; // no courses: nothing to filter

  var list = root.querySelector('[data-catalog-list]');
  var count = root.querySelector('[data-catalog-count]');
  var empty = root.querySelector('[data-catalog-empty]');
  var reset = root.querySelector('[data-catalog-reset]');
  var sortSelect = form.elements.sort; // outside the form element, linked by form=""

  var LEVELS = ['beginner', 'intermediate', 'advanced']; // difficulty order
  var ACCESS = ['free', 'paid'];
  var SORTS = ['difficulty', 'new', 'old']; // '' = «Рекомендуемые»
  var DEFAULTS = { q: '', level: '', access: '', discount: false, sort: '' };

  // Same normalization as normalize_title() in backend/views.py.
  function normalize(text) {
    return text.toLowerCase().replace(/ё/g, 'е').split(/\s+/).filter(Boolean).join(' ');
  }

  var courses = Array.prototype.map.call(list.children, function (item) {
    var oldPrice = item.getAttribute('data-old-price');
    var level = item.getAttribute('data-level');
    return {
      item: item,
      title: item.getAttribute('data-title'),
      level: level,
      levelRank: level ? LEVELS.indexOf(level) : LEVELS.length, // no level: last
      price: parseFloat(item.getAttribute('data-price')),
      oldPrice: oldPrice === '' ? null : parseFloat(oldPrice),
      created: item.getAttribute('data-created'), // fixed-width UTC: compare as strings
      rank: parseInt(item.getAttribute('data-rank'), 10),
      id: item.getAttribute('data-id'),
    };
  });

  function compareStrings(a, b) {
    return a < b ? -1 : a > b ? 1 : 0;
  }

  var COMPARE = {
    '': function (a, b) { return a.rank - b.rank; },
    difficulty: function (a, b) { return a.levelRank - b.levelRank || a.rank - b.rank; },
    new: function (a, b) { return compareStrings(b.created, a.created) || compareStrings(a.id, b.id); },
    old: function (a, b) { return compareStrings(a.created, b.created) || compareStrings(a.id, b.id); },
  };

  function matches(course, state, query) {
    if (query && course.title.indexOf(query) === -1) return false;
    if (state.level && course.level !== state.level) return false;
    if (state.access === 'free' && course.price !== 0) return false;
    if (state.access === 'paid' && !(course.price > 0)) return false;
    if (state.discount && !(course.oldPrice !== null && course.oldPrice > course.price)) return false;
    return true;
  }

  function oneOf(value, allowed) {
    return allowed.indexOf(value) !== -1 ? value : '';
  }

  function readUrl() {
    var params = new URLSearchParams(window.location.search);
    return {
      q: (params.get('q') || '').slice(0, 100),
      level: oneOf(params.get('level'), LEVELS),
      access: oneOf(params.get('access'), ACCESS),
      discount: params.get('discount') === '1',
      sort: oneOf(params.get('sort'), SORTS),
    };
  }

  function writeUrl(state) {
    // Other parameters (utm_… etc.) are kept as they are.
    var params = new URLSearchParams(window.location.search);
    function put(name, value) {
      if (value) params.set(name, value); else params.delete(name);
    }
    put('q', state.q.trim() ? state.q : '');
    put('level', state.level);
    put('access', state.access);
    put('discount', state.discount ? '1' : '');
    put('sort', state.sort);
    var query = params.toString();
    var url = window.location.pathname + (query ? '?' + query : '') + window.location.hash;
    if (url !== window.location.pathname + window.location.search + window.location.hash) {
      try {
        window.history.replaceState(window.history.state, '', url);
      } catch (e) {
        // Some embedded browsers forbid it: filtering still works.
      }
    }
  }

  function readForm() {
    return {
      q: form.elements.q.value,
      level: form.elements.level.value,
      access: form.elements.access.value,
      discount: form.elements.discount.checked,
      sort: sortSelect.value,
    };
  }

  // Checks the radio with this value. Not RadioNodeList.value = '': Chrome
  // leaves the group as it was for the empty value («Любой», «Все»).
  function checkRadio(name, value) {
    Array.prototype.forEach.call(form.elements[name], function (radio) {
      radio.checked = radio.value === value;
    });
  }

  function writeForm(state) {
    form.elements.q.value = state.q;
    checkRadio('level', state.level);
    checkRadio('access', state.access);
    form.elements.discount.checked = state.discount;
    sortSelect.value = state.sort;
  }

  function render(state) {
    var query = normalize(state.q);
    var shown = 0;
    var sorted = courses.slice().sort(COMPARE[state.sort]);
    var reorder = sorted.some(function (course, i) { return list.children[i] !== course.item; });
    sorted.forEach(function (course) {
      var visible = matches(course, state, query);
      course.item.hidden = !visible;
      if (visible) shown += 1;
      if (reorder) list.appendChild(course.item); // moves it: the list ends up in sorted order
    });
    if (count.textContent !== String(shown)) count.textContent = String(shown);
    empty.hidden = shown !== 0;
  }

  function update() {
    var state = readForm();
    render(state);
    writeUrl(state);
  }

  form.addEventListener('input', update);
  form.addEventListener('change', update);
  sortSelect.addEventListener('change', update); // the select is outside <form>
  form.addEventListener('submit', function (event) {
    event.preventDefault(); // Enter in the search box: already filtered
  });
  reset.addEventListener('click', function () {
    writeForm(DEFAULTS);
    update();
  });

  // Start from the URL, then show the controls.
  var initial = readUrl();
  writeForm(initial);
  render(initial);
  writeUrl(initial); // drops invalid values from the address
  root.classList.add('is-enhanced');
  form.hidden = false;
  root.querySelector('[data-catalog-toolbar]').hidden = false;
})();
