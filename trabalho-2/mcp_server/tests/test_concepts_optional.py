"""A busca sem índice deve funcionar também no perfil sem dependências RAG."""
import os
from pathlib import Path
import subprocess
import sys


def test_sem_indice_nao_depende_de_chroma(tmp_path):
    ambiente = {**os.environ, "CHROMA_PATH": str(tmp_path / "indice-nao-criado")}
    # -S impede o carregamento de site-packages, onde o Chroma é instalado.
    script = """
from mcp_server.tools.concepts import buscar_conceitos
assert buscar_conceitos('garfo', tema='garfo') == []
assert buscar_conceitos('   ') == []
try:
    buscar_conceitos('garfo', k=0)
except ValueError:
    pass
else:
    raise AssertionError('k inválido deveria ser rejeitado')
"""
    resultado = subprocess.run([sys.executable, "-S", "-c", script],
                               cwd=Path(__file__).resolve().parents[2], env=ambiente,
                               capture_output=True, text=True, timeout=10)
    assert resultado.returncode == 0, resultado.stderr
