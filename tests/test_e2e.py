"""E2E: sobe uma Roda Conversora ISOLADA (outro app id, config e log em pasta temporária, sem
ícone na barra, pausada = sem pegar o botão do mouse) e manda conversões pela linha de comando,
do jeito que o menu do Nautilus faz. Confere o arquivo gerado e o log.

Não encosta na roda que estiver rodando no dia a dia. Precisa de sessão gráfica (DISPLAY).
"""

import glob
import json
import os
import shutil
import subprocess
import time
import unittest

from amostras import RAIZ, TEM_FFMPEG, faixas, gerar, pasta_temporaria

APP = os.path.join(RAIZ, "roda_conversor.py")


@unittest.skipUnless(os.environ.get("DISPLAY"), "e2e precisa de sessão gráfica")
class TestE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = pasta_temporaria()
        cls.a = gerar(cls.dir)
        cfg = os.path.join(cls.dir, "config")
        os.makedirs(cfg)
        with open(os.path.join(cfg, "config.json"), "w") as f:
            json.dump({"pausado": True}, f)  # pausada: não disputa o botão com a roda de verdade
        cls.log = os.path.join(cls.dir, "roda.log")
        cls.env = dict(os.environ, RODA_APP_ID=f"br.local.RodaConversora.Teste{os.getpid()}",
                       RODA_CONFIG_DIR=cfg, RODA_LOG=cls.log, RODA_SEM_BANDEJA="1",
                       PYTHONDONTWRITEBYTECODE="1")
        # stderr num arquivo, não num PIPE: pipe que ninguém lê enche e trava a roda no meio do teste
        cls.err_path = os.path.join(cls.dir, "stderr.txt")
        cls.err = open(cls.err_path, "w")
        cls.proc = subprocess.Popen(["/usr/bin/python3", APP, "--desligado"], env=cls.env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=cls.err, start_new_session=True)
        fim = time.time() + 15
        while time.time() < fim and not cls._no_log("iniciado"):
            time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()  # pelo PID do Popen, nunca pkill -f
        try:
            cls.proc.wait(5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.err.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def _no_log(cls, texto):
        return texto in cls._ler(cls.log)

    def mandar(self, *args):
        """Segunda chamada com o mesmo app id: o GApplication repassa pra instância de teste."""
        r = subprocess.run(["/usr/bin/python3", APP, *args], env=self.env, timeout=20,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    @classmethod
    def _ler(cls, caminho):
        try:
            with open(caminho, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def esperar(self, padrao, timeout=40):
        """Pronto = o log da roda registrou "ok ... -> <arquivo>" (arquivo só existir não basta:
        o ffmpeg ainda pode estar escrevendo)."""
        fim = time.time() + timeout
        while time.time() < fim:
            log = self._ler(self.log)
            for f in glob.glob(os.path.join(self.dir, padrao)):
                if f"-> {f}" in log:
                    return f
            self.assertIsNone(self.proc.poll(), "a roda de teste morreu: " + self._ler(self.err_path)[-2000:])
            time.sleep(0.3)
        self.fail(f"não gerou {padrao}; log:\n{self._ler(self.log)}\nstderr:\n{self._ler(self.err_path)[-2000:]}")

    def test_0_instancia_subiu_isolada(self):
        self.assertIsNone(self.proc.poll())
        self.assertTrue(self._no_log("iniciado"))

    def test_grade_de_imagens(self):
        from PIL import Image
        self.mandar("--alvo=juntar:GRADE:montagem", self.a["vermelha.jpg"], self.a["verde.png"],
                    self.a["azul_alfa.png"])
        f = self.esperar("vermelha - grade montagem*.png")
        with Image.open(f) as im:
            self.assertGreater(im.width, 256)

    def test_converter_um_a_um(self):
        self.mandar("--alvo=imagem:WEBP:", self.a["vermelha.jpg"], self.a["verde.png"])
        self.esperar("vermelha.webp")
        self.esperar("verde.webp")

    def test_unir_videos(self):
        if not TEM_FFMPEG:
            self.skipTest("sem ffmpeg")
        self.mandar("--alvo=juntar:UNIR:um depois do outro", self.a["v1.mp4"], self.a["v2_mudo.mp4"])
        f = self.esperar("v1 - unir um depois do outro*.mp4")
        self.assertEqual(faixas(f), ["audio", "video"])

    def test_alvo_inexistente_so_loga(self):
        self.mandar("--alvo=juntar:NAO:existe", self.a["vermelha.jpg"], self.a["verde.png"])
        fim = time.time() + 10
        while time.time() < fim and not self._no_log("alvo não encontrado"):
            time.sleep(0.2)
        self.assertTrue(self._no_log("alvo não encontrado"))
        self.assertIsNone(self.proc.poll())


if __name__ == "__main__":
    unittest.main()
