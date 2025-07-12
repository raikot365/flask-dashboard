// Función para descargar el Excel según los parámetros actuales
    function descargarExcel(params) {
        const query = new URLSearchParams(params).toString();
        window.location.href = `/api/xls?${query}`;
    }

    document.addEventListener('DOMContentLoaded', function() {
        const btnDescargar = document.getElementById('btn-descargar-xls');
        const btnRango = document.getElementById('customRangeBtn');
        const rangoMsg = document.getElementById('rangoMsg');
        const startInput = document.getElementById('startDate');
        const endInput = document.getElementById('endDate');
        const maquinaSelectElem = document.getElementById('maquinaSelect');

        // Mostrar mensaje cuando se selecciona un rango válido
        btnRango.addEventListener('click', function(e) {
            e.preventDefault();
            const start = startInput.value;
            const end = endInput.value;
            const maquina = maquinaSelectElem.value;
            if (start && end) {
                rangoMsg.classList.remove('d-none');
                rangoMsg.classList.add('show');
                rangoMsg.innerHTML = '<i class="bi bi-info-circle"></i> Selección actual: <strong>' + start.replace('T',' ') + '</strong> a <strong>' + end.replace('T',' ') + '</strong> para <strong>'+ maquina.replace() + '</strong>';
            } else {
                rangoMsg.classList.add('d-none');
            }
        });

        // Botón de descarga Excel
        btnDescargar.addEventListener('click', function(e) {
            e.preventDefault();
            const start = startInput.value;
            const end = endInput.value;
            const maquina = maquinaSelectElem.value;
            let params = {};
            if (start && end) {
                params = { start, end, maquina};
            } else {
                // Si hay selectores de fecha/turno, puedes agregarlos aquí si existen en el HTML
                const datePicker = document.getElementById('datePicker');
                const turnoSelect = document.getElementById('turnoSelect');
                if (datePicker && turnoSelect) {
                    const date = datePicker.value;
                    const turno = turnoSelect.value;
                    if (date && turno) {
                        params = { date, turno, maquina };
                    } else {
                        alert('Por favor completá los campos requeridos.');
                        return;
                    }
                } else {
                    alert('Por favor completá los campos requeridos.');
                    return;
                }
            }
            descargarExcel(params);
        });
    });