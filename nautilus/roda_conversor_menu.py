"""Botão direito do Nautilus → "Converter para ▸" com os mesmos alvos da roda.

Instalado pelo instalar.sh em ~/.local/share/nautilus-python/extensions/ (precisa do
pacote python3-nautilus). @DIR@ é trocado pela pasta do projeto na instalação.
Só monta o menu: a conversão roda no processo da Roda Conversora (--alvo=<chave>).
"""

import os
import subprocess
import sys

import gi

gi.require_version("Nautilus", "4.0")
from gi.repository import GObject, Nautilus  # noqa: E402

DIR = "@DIR@"
sys.path.insert(0, DIR)
LIMITE = 400  # seleção gigante: não monta menu (cada arquivo é inspecionado)


def _rotulo(a):
    return f"{a.rotulo} ({a.sub})" if a.sub else a.rotulo


class MenuRoda(GObject.GObject, Nautilus.MenuProvider):
    def _rodar(self, _item, caminhos, args):
        subprocess.Popen(["/usr/bin/python3", os.path.join(DIR, "roda_conversor.py")] + args + caminhos,
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _item(self, nome, rotulo, caminhos, args):
        it = Nautilus.MenuItem(name=f"RodaConversora::{nome}", label=rotulo)
        it.connect("activate", self._rodar, caminhos, args)
        return it

    def _sub(self, nome, rotulo):
        it = Nautilus.MenuItem(name=f"RodaConversora::{nome}", label=rotulo)
        menu = Nautilus.Menu()
        it.set_submenu(menu)
        return it, menu

    def get_file_items(self, files):
        caminhos = [f.get_location().get_path() for f in files if f.get_uri_scheme() == "file"]
        caminhos = [c for c in caminhos if c]
        if not caminhos or len(caminhos) > LIMITE:
            return []
        try:
            import conversores as conv
            mesma = len({conv.familia_de(c) for c in caminhos}) == 1
            um_a_um = conv.alvos_para(caminhos[0]) if mesma else []
            juntar = conv.alvos_juntar(caminhos)
        except Exception:  # nunca derrubar o Nautilus por causa do menu
            return []
        if not um_a_um and not juntar:
            return []
        raiz, menu = self._sub("raiz", "Converter para")
        for i, a in enumerate(um_a_um):
            menu.append_item(self._item(f"c{i}", _rotulo(a), caminhos, [f"--alvo={a.chave}"]))
        if juntar:
            it, sub = self._sub("juntar", f"Juntar os {len(caminhos)} em um")
            for i, a in enumerate(juntar):
                sub.append_item(self._item(f"j{i}", _rotulo(a), caminhos, [f"--alvo={a.chave}"]))
            menu.append_item(it)
        it, sub = self._sub("ajustes", "Com ajustes…")
        for i, a in enumerate(um_a_um + juntar):
            pre = "Juntar: " if a.junta else ""
            sub.append_item(self._item(f"a{i}", pre + _rotulo(a), caminhos, [f"--alvo={a.chave}", "--ajustes"]))
        menu.append_item(it)
        menu.append_item(self._item("roda", "Abrir a roda…", caminhos, []))
        return [raiz]
