# CLAUDE.md - Roda Conversora

Regras e contexto para qualquer agente que mexer aqui. Leia inteiro antes de editar.
Mesmo molde do projeto Monitor flutuante: Python + GTK3 do sistema, sem pip.

## O que é

Segura o clique da rodinha do mouse (padrão: botão 2, desde 2026-10-26; antes era o lateral 8) sobre um arquivo no Nautilus ou na área de
trabalho, aparece uma roda estilo GTA V com os formatos possíveis. Solta no anel de dentro =
converte direto, mesmo nome, extensão nova, `nome (1).ext` se já existir. Solta no anel de fora
(⚙) = tela de ajustes daquele formato. Solta no centro ou a mais de `Roda.FORA` (24 px) além da borda = cancela, nada fica marcado. Toque rápido = roda fica
aberta, escolhe com clique esquerdo, direito cancela. Cada conversão abre uma tela no canto superior direito:
carregando (barra) → sucesso (fecha na hora, sem botões) ou erro + "Como resolver" + detalhes.

Tratamento com o usuário: direto. É Ubuntu, **não Windows**.

## Ambiente alvo (conferido em 2026-10-25)

- Ubuntu 24.04, GNOME, **X11**, extensão DING (ícones da área de trabalho, janela classe `Gjs`,
  título `Desktop Icons N`). Dois monitores empilhados (1920x2160 de root).
- Tem: ffmpeg 6.1 (x264, vpx, aom, svtav1, opus, vorbis, lame), soffice, gs, pdftotext,
  PIL (webp sim, avif não), PyMuPDF (`fitz`), `markdown`, `yaml`, fontTools + brotli,
  libX11/libXtst/libXi, loader SVG/HEIF/WebP do GdkPixbuf.
- Não tem: python3-gi-cairo, xdotool, xclip, ImageMagick, pandoc, python-xlib.

## Regras do projeto

1. **Zero dependência nova.** Precisa de pacote? Escreva o `sudo apt install` e entregue.
2. **Sem cairo** (o `draw` quebra sem python3-gi-cairo). A roda é SVG → `GdkPixbuf.PixbufLoader`.
3. **Nunca deixar o ponteiro congelado.** O grab do botão é `GrabModeSync`: todo ButtonPress
   passivo precisa de `XAllowEvents` (Replay fora do gerenciador de arquivos, Async dentro).
   A roda tem timeout de 45 s e solta o grab em qualquer exceção.
4. **Fora do Nautilus/DING o clique é repassado** (`ReplayPointer`): o "voltar" do navegador
   continua funcionando. Não troque isso por grab async direto.
5. **Nunca sobrescrever arquivo do usuário.** Saída sempre por `caminho_livre` (incremento).
   O único `os.remove` apaga o parcial que a própria conversão criou quando ela falha.
6. Erro vira `ErroConversao(motivo, sugestao, detalhes)`. Toda falha nova conhecida ganha
   regra em `erro_de_processo` com sugestão concreta.
7. Lixo vai para `./lixo/` (ignorado pelo git), nada de `rm`.

## Arquitetura

| Arquivo / parte | O que faz |
|---|---|
| `conversores.py` | motor sem GTK: `Alvo`, `Opcao`, `alvos_para(caminho)`, `converter()`, `ErroConversao`, `Progresso` (lê `-progress` do ffmpeg, cancela por `killpg`) |
| famílias | imagem (PIL; AVIF via ffmpeg/libaom; HEIC lido pelo GdkPixbuf), svg (fitz), áudio/vídeo (ffmpeg), pdf (fitz + gs pra comprimir), texto/md/html (markdown + fitz.Story pro PDF), office (soffice com perfil temporário próprio), dados json/yaml/csv/tsv/toml, legenda srt/vtt/ass, fonte ttf/otf/woff/woff2, pacote zip/tar.* e pasta → pacote |
| `roda_conversor.py` `X11` | libX11 por ctypes: `XGrabButton` no root, `XGrabPointer` com a roda aberta, `XQueryTree`+`XGetClassHint` pra saber a janela, XTest pra clique/Ctrl+C |
| `Captura` | guarda o texto da área de transferência, põe sentinela, Ctrl+C falso, lê `x-special/gnome-copied-files` (ou texto), restaura o texto antigo |
| `Roda` | janela POPUP RGBA; `zona(x,y)` → (índice, `conv`/`cfg`); parada, re-renderiza só quando muda; animada, redesenha a ~60 fps (quadro ~6 ms) |
| extras | `Alvo(extra=True)` sai da roda principal e vai pra 2ª roda atrás da pétala `+ MAIS` (familia `menu`, func `None`); soltar/clicar nela ou parar 0,45 s em cima troca; `← VOLTAR` volta |
| `TelaTarefa` | uma por conversão, empilhadas no canto superior direito do monitor primário |
| `TelaAjustes` | campos gerados das `Opcao` do alvo + nome + pasta + "lembrar ajustes" |
| `TelaConfig` | botão (com detecção por clique), tamanho da roda, pasta fixa |

Config: `~/.config/roda-conversor/config.json` (merge sobre `PADRAO`). Log:
`~/.cache/roda-conversor/roda.log`.

## Como testar depois de mexer

1. `./verifica.sh` (ou `--office`): compila, renderiza a roda em PNG e roda ~33 conversões em
   amostras minúsculas em `tmp/verifica/` (ignorado pelo git). Tem que sair `OK`.
2. Reiniciar: `ferramentas/subir.sh` (script próprio, log em `tmp/app.log`; **não**
   cole `pgrep -f roda_conversor` num `bash -c`, ele mata o próprio shell, exit 144).
3. Print das telas: `python3 ferramentas/print_telas.py` (depois do `./verifica.sh`).
4. O gatilho real (botão físico + Nautilus) **não** se testa por script: XTest falso clicaria
   na tela do usuário em uso. Peça pro usuário testar.

## Armadilhas conhecidas

- **Ctrl+C falso SÓ com foco no gerenciador de arquivos** (`X11.foco()` + `e_gerenciador`), e
  uma vez só. Em 2026-10-25 a versão antiga mandava Ctrl+C pra janela focada sem conferir (e uma
  2ª vez aos 350 ms): caiu no terminal e **fechou o Claude Code do usuário**. Nunca afrouxar.
- **Foco antes do Ctrl+C:** na área de trabalho (DING) o clique falso às vezes não leva o foco
  (fica no terminal). `X11.focar(janela)` faz `XSetInputFocus` no cliente achado por `classe()`.
- **Animação curta** (abrir 0,15 s, escolher 0,2 s, fechar 0,1 s): o usuário achou lenta a de 0,4 s.
- **Nunca mover o cursor.** A roda abre centrada no mouse mesmo perto da borda (fica cortada).
  A versão que empurrava a roda pra caber no monitor fazia o cursor pular ~2 dedos (os dois
  monitores do usuário são empilhados: a divisa também é borda). `X11.mover` ficou sem uso.
- **Fila interna da Xlib congela o mouse.** O grab passivo é síncrono: até o `XAllowEvents`, o
  ponteiro do PC inteiro fica parado. Chamada com resposta (XQueryPointer, XSync) pode puxar o
  ButtonPress pra fila da Xlib sem o fd acordar o `io_add_watch`; por isso há um dreno de 20 ms
  (`GLib.timeout_add(20, self._ler)`). Era a causa do "aperto e demora pra reagir". Não remover.

- **Animação** (`Roda._petala`/`_miolo`): abrir = pétalas desabrocham em sequência girando
  (ease-out-back); escolher = as outras giram até a escolhida pelo caminho mais curto e somem,
  ela pulsa; fechar = recolhe. O grab do mouse é solto na hora: a animação nunca segura o
  ponteiro. Mantenha o quadro < 16 ms (`verifica.sh` mede e salva `animacao.png`).

- **Nada de notificação.** Janela toplevel que abre sem foco faz o GNOME soltar "está pronto".
  Por isso a `TelaTarefa` é POPUP (override-redirect) e ajustes/config abrem por `apresentar()`
  (foco com o horário do servidor X). Não volte a tela de progresso pra TOPLEVEL.
- **Abrir rápido.** A roda só aparece quando o formato já é conhecido (fallback "lendo…" aos
  300 ms). A captura não espera timer: texto antigo fica em cache pelo `owner-change`, Ctrl+C
  sai 40 ms após o clique e a resposta chega pelo sinal. O log grava o tempo de cada captura.
- PDF → "1 imagem" emenda as páginas; acima de 150 MP ou do lado máximo do formato (JPEG 65500)
  o DPI baixa sozinho, pra não derrubar o PC.

- O Ctrl+C falso troca a área de transferência; só o **texto** anterior é restaurado.
- Se outro programa já prendeu o botão (input-remapper, Solaar), `XGrabButton` dá BadAccess:
  o app avisa e sugere trocar o botão.
- Wayland: nada disso funciona (grab global e XTest são X11). Seria preciso evdev/portal.
- Escala HiDPI ≠ 1 não foi testada.

## Ideias não feitas (só se o usuário pedir)

- Lote: segurar com vários arquivos selecionados sem perder a seleção (hoje o clique falso
  seleciona só o de baixo do cursor; lote funciona pelo script do Nautilus).
- OCR de PDF escaneado (sugestão já aponta `ocrmypdf`).
- Remover fundo de imagem, upscale, juntar PDFs.

## Ícone e ligado/desligado (2026-10-27)

- Ícone próprio na barra: roda de 6 fatias com seta (SVG gerado em
  `~/.cache/roda-conversor/icones/`), colorido = ligada, cinza = pausada.
- **Sem item "Sair"**: o ícone fica sempre na barra; desligar = desmarcar "Ligada"
  (mesmo `cfg["pausado"]` de antes). Autostart roda com `--desligado` (sobe pausada).
