// roster/static/roster/js/roles_operador.js

// Script complementario para poblar el selector de roles operacionales en el modal de operador
document.addEventListener('DOMContentLoaded', () => {
    const btnOpenOperador = document.getElementById('btnOpenOperadorModal');
    if (btnOpenOperador) {
        const originalClick = btnOpenOperador.onclick;
        btnOpenOperador.addEventListener('click', async () => {
            try {
                const res = await fetch('/api/roles-operador/?_ts=' + new Date().getTime(), { cache: 'no-store' });
                if (res.ok) {
                    const roles = await res.json();
                    const selectRol = document.getElementById('operadorRolSelect');
                    if (selectRol) {
                        selectRol.innerHTML = '<option value="">-- Seleccione Rol / Competencia --</option>';
                        roles.filter(r => r.activo).forEach(r => {
                            selectRol.innerHTML += `<option value="${r.id}">${r.nombre}</option>`;
                        });
                    }
                }
            } catch (err) {
                console.error("Error al cargar catálogo de roles para el operador:", err);
            }
        });
    }
});
