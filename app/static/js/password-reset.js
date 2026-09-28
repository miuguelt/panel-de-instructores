(function () {
    const token = document.getElementById('token');
    const fragment = window.location.hash.slice(1);
    if (token && fragment) {
        token.value = fragment;
        window.history.replaceState(null, '', window.location.pathname);
    }
})();
