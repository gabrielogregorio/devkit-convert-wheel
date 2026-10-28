"""Translations. English is the source language; Brazilian Portuguese comes from PT_BR.

The language follows the desktop the same way gettext does (LANGUAGE, LC_ALL, LC_MESSAGES,
LANG, first one set wins). CONVERT_WHEEL_LANG overrides it, e.g. CONVERT_WHEEL_LANG=en.
Any "pt*" locale gets pt-BR; everything else gets English.

tr("text") translates now. tr_noop("text") only marks a string that is stored in English
and translated when shown (target labels: they also name the remembered settings).
check.sh fails if a marked string has no PT_BR entry or its {placeholders} differ.
"""
import os


def _detect():
    for var in ("CONVERT_WHEEL_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value:
            return value.split(":")[0].lower()
    return ""


LANG = "pt" if _detect().startswith("pt") else "en"
HTML_LANG = "pt-BR" if LANG == "pt" else "en"


def tr(text):
    return PT_BR.get(text, text) if LANG == "pt" else text


def tr_noop(text):
    return text


def decimal(text):
    """'1.5 MB' -> '1,5 MB' in pt-BR."""
    return text.replace(".", ",") if LANG == "pt" else text


PT_BR = {
    # ---- app, tray and wheel
    "Convert Wheel": "Roda Conversora",
    "{app} (paused)": "{app} (pausada)",
    "{app} - settings": "{app} - configurações",
    "Enabled": "Ligada",
    "Convert file…": "Converter arquivo…",
    "Settings…": "Configurações…",
    "Open log": "Abrir log",
    "File to convert": "Arquivo para converter",
    "+ MORE": "+ MAIS",
    "← BACK": "← VOLTAR",
    "main": "principais",
    "{n} extras": "{n} extras",
    "folder": "pasta",
    "release: cancel": "solte: cancelar",
    "⚙ adjust {label}": "⚙ ajustar {label}",
    "reading file…": "lendo arquivo…",
    "no file here": "nenhum arquivo aqui",
    ".{ext}: no conversion": ".{ext} sem conversão",
    "Mouse button {n} is already grabbed by another program.":
        "O botão {n} do mouse já está capturado por outro programa.",
    "Close the program that uses this button (e.g. input-remapper, Solaar, easystroke) or pick another "
    "button in Settings.":
        "Feche o programa que usa esse botão (ex.: input-remapper, Solaar, easystroke) ou escolha outro "
        "botão em Configurações.",
    "How to fix: {hint}": "Como resolver: {hint}",

    # ---- progress popup
    "converting…": "convertendo…",
    "converting… {pct}%": "convertendo… {pct}%",
    "conversion failed": "a conversão falhou",
    "How to fix": "Como resolver",
    "Technical details": "Detalhes técnicos",
    "(no details)": "(sem detalhes)",
    "Try again through ⚙ (outer ring) with other settings.":
        "Tente de novo pelo ⚙ (anel externo) com outros ajustes.",
    "Copy error": "Copiar erro",
    "Adjust and retry": "Ajustar e tentar",
    "Close": "Fechar",
    "Cancel": "Cancelar",
    "cancelling…": "cancelando…",
    "error copied to the clipboard": "erro copiado para a área de transferência",

    # ---- per-format settings dialog
    "Adjust conversion → {label}": "Ajustar conversão → {label}",
    "to {label}": "para {label}",
    "File name": "Nome do arquivo",
    "Folder": "Pasta",
    "Output folder": "Pasta de saída",
    "+{n} more file(s): same settings, automatic name": "+{n} arquivo(s): mesmo ajuste, nome automático",
    "Remember these settings for quick convert": "Lembrar estes ajustes para o converter rápido",
    "This format has no settings; only name and folder.": "Esse formato não tem ajustes; só nome e pasta.",
    "Convert": "Converter",

    # ---- app settings dialog
    "Mouse button": "Botão do mouse",
    "Back side button (8)": "Lateral de trás (8)",
    "Front side button (9)": "Lateral da frente (9)",
    "Middle / wheel click (2)": "Meio / rodinha (2)",
    "Button {n}": "Botão {n}",
    "or click HERE with the button you want to use": "ou clique AQUI com o botão que quer usar",
    "detected: button {n}": "detectado: botão {n}",
    "The left/right button cannot be the trigger.": "Botão esquerdo/direito não pode ser o gatilho.",
    "Wheel size (%)": "Tamanho da roda (%)",
    "Fixed output folder": "Pasta de saída fixa",
    "Same as the file": "Mesma do arquivo",
    "Forget remembered settings ({n})": "Esquecer ajustes lembrados ({n})",
    "Save": "Salvar",
    "Hold the button over a file in Nautilus or on the desktop, drag to the format and release. Inner "
    "ring: converts right away. Outer ring (⚙): opens the settings. Release in the center or far from "
    "the wheel to cancel. A quick tap on the button keeps the wheel open: pick with the left click, the "
    "right click cancels.":
        "Segure o botão sobre um arquivo no Nautilus ou na área de trabalho, arraste até o formato e "
        "solte. Anel de dentro: converte direto. Anel de fora (⚙): abre os ajustes. Solte no centro ou "
        "longe da roda para cancelar. Toque rápido no botão deixa a roda aberta: escolha com clique "
        "esquerdo, direito cancela.",

    # ---- petal sub-labels
    "icon": "ícone",
    "animation": "animação",
    "animated": "animado",
    "audio": "áudio",
    "1 frame": "1 quadro",
    "pages": "páginas",
    "1 image": "1 imagem",
    "approximate": "aproximado",
    "compress": "comprimir",
    "pack": "compactar",
    "vector": "vetor",
    "multipage": "multipágina",
    "1st slide": "1º slide",
    "1st sheet": "1ª aba",
    "spreadsheet": "planilha",
    "web": "web",

    # ---- option labels and choices
    "White": "Branco",
    "Black": "Preto",
    "Gray": "Cinza",
    "None": "Nenhuma",
    "Original": "Original",
    "22.05 kHz": "22,05 kHz",
    "44.1 kHz": "44,1 kHz",
    "Mono": "Mono",
    "Stereo": "Estéreo",
    "High (large file)": "Alta (arquivo grande)",
    "Medium": "Média",
    "Low": "Baixa",
    "Minimum": "Mínima",
    "Fast": "Rápido",
    "Balanced": "Médio",
    "Slow (smaller file)": "Lento (menor arquivo)",
    "Width (px, 0 = original)": "Largura (px, 0 = original)",
    "Height (px, 0 = proportional)": "Altura (px, 0 = proporcional)",
    "Scale (%) when width/height = 0": "Escala (%) se largura/altura = 0",
    "Quality (1-100)": "Qualidade (1-100)",
    "Background instead of transparency": "Fundo no lugar da transparência",
    "Keep EXIF metadata (camera, GPS)": "Manter metadados EXIF (câmera, GPS)",
    "PNG compression (0-9)": "Compressão PNG (0-9)",
    "Progressive JPEG": "JPEG progressivo",
    "Lossless": "Sem perdas (lossless)",
    "Compression": "Compressão",
    "Sizes (px, comma separated)": "Tamanhos (px, separados por vírgula)",
    "Page DPI": "DPI da página",
    "Width (px, 0 = use the scale)": "Largura (px, 0 = usa a escala)",
    "Scale (%)": "Escala (%)",
    "Quality": "Qualidade",
    "Background": "Fundo",
    "Base resolution (px)": "Resolução base (px)",
    "Sizes": "Tamanhos",
    "Quality (bitrate)": "Qualidade (bitrate)",
    "Sample rate": "Taxa de amostragem",
    "Channels": "Canais",
    "Trim: start (e.g. 0:30)": "Cortar: início (ex. 0:30)",
    "Trim: end (e.g. 2:10)": "Cortar: fim (ex. 2:10)",
    "Trim: start": "Cortar: início",
    "Trim: end": "Cortar: fim",
    "Volume (%)": "Volume (%)",
    "Normalize loudness (loudnorm -16 LUFS)": "Normalizar volume (loudnorm -16 LUFS)",
    "Resolution": "Resolução",
    "Frames per second": "Quadros por segundo",
    "Encoding speed": "Velocidade de codificação",
    "Remove the audio": "Remover o áudio",
    "Copy without re-encoding (fast, ignores resolution/quality)":
        "Copiar sem recodificar (rápido, ignora resolução/qualidade)",
    "Width": "Largura",
    "Loop forever": "Repetir em loop",
    "Frame time (e.g. 0:05)": "Instante do quadro (ex. 0:05)",
    "Resolution (DPI)": "Resolução (DPI)",
    "Pages (empty = all; e.g. 1-3,5)": "Páginas (vazio = todas; ex. 1-3,5)",
    "Join every page into a single image": "Juntar todas as páginas numa imagem só",
    "Join as": "Juntar em",
    "Column (one below the other)": "Coluna (uma embaixo da outra)",
    "Row (side by side)": "Linha (lado a lado)",
    "Space between pages (px)": "Espaço entre páginas (px)",
    "Space color": "Cor do espaço",
    "Mark page breaks (\\f)": "Marcar quebra de página (\\f)",
    "Level": "Nível",
    "Maximum (72 dpi, screen)": "Máximo (72 dpi, tela)",
    "Medium (150 dpi)": "Médio (150 dpi)",
    "Light (300 dpi, print)": "Leve (300 dpi, impressão)",
    "Text as curves (faithful, not editable)": "Texto como curvas (fiel, não editável)",
    "Page size": "Tamanho da página",
    "Letter": "Carta",
    "Font size (pt)": "Tamanho da fonte (pt)",
    "Margin (mm)": "Margem (mm)",
    "Use the file name as # title": "Pôr o nome do arquivo como título #",
    "Indentation (0 = compact)": "Indentação (0 = compacto)",
    "Separator": "Separador",
    "Comma": "Vírgula",
    "Semicolon": "Ponto e vírgula",
    "Pipe |": "Barra |",
    "Input encoding": "Codificação da entrada",
    "Windows-1252 (old Western subtitles)": "Windows-1252 (legenda antiga BR)",

    # ---- progress texts
    "page {n} of {total}": "página {n} de {total}",
    "page {n}": "página {n}",
    "{n} pages → {w}×{h} px, saving…": "{n} páginas → {w}×{h} px, gravando…",
    "image too large: lowered to {dpi} DPI": "imagem grande demais: baixei para {dpi} DPI",
    "{t}s is past the end ({dur}s): used the middle of the video":
        "instante {t}s passa do fim ({dur}s): usei o meio do vídeo",
    "ghostscript compressing…": "ghostscript comprimindo…",
    "LibreOffice converting…": "LibreOffice convertendo…",
    "extracting…": "extraindo…",
    "packing…": "empacotando…",

    # ---- errors (reason)
    "Tool '{exe}' is not installed.": "Ferramenta '{exe}' não está instalada.",
    "'{exe}' exited with an error (code {code}).": "'{exe}' terminou com erro (código {code}).",
    "Disk full.": "Disco cheio.",
    "No permission to read or write.": "Sem permissão para ler ou gravar.",
    "The file does not look like valid media (corrupted or wrong extension).":
        "O arquivo não parece ser mídia válida (corrompido ou extensão errada).",
    "Incomplete video (interrupted download or recording).": "Vídeo incompleto (download ou gravação interrompida).",
    "This ffmpeg lacks the required encoder.": "Este ffmpeg não tem o codificador necessário.",
    "The file does not have the requested track (e.g. video without audio).":
        "O arquivo não tem a faixa pedida (ex.: vídeo sem áudio).",
    "The output format does not accept the file's codecs.": "O formato de saída não aceita os codecs do arquivo.",
    "Password-protected PDF.": "PDF protegido por senha.",
    "This codec does not accept an odd resolution.": "Resolução ímpar não é aceita por esse codec.",
    "LibreOffice could not open the document.": "O LibreOffice não conseguiu abrir o documento.",
    "Could not open the image (corrupted or unsupported format).":
        "Não consegui abrir a imagem (corrompida ou formato não suportado).",
    "This file has no audio track.": "Esse arquivo não tem faixa de áudio.",
    "Invalid time '{txt}'.": "Tempo '{txt}' inválido.",
    "Invalid pages '{spec}'.": "Páginas '{spec}' inválidas.",
    "No valid page in '{spec}' (the PDF has {total}).": "Nenhuma página válida em '{spec}' (o PDF tem {total}).",
    "Could not open the PDF (corrupted?).": "Não consegui abrir o PDF (corrompido?).",
    "The PDF has no selectable text (it is a scanned image).":
        "O PDF não tem texto selecionável (é imagem escaneada).",
    "Text to .{ext} is not implemented.": "Conversão de texto para .{ext} não implementada.",
    "LibreOffice is not installed.": "LibreOffice não está instalado.",
    "LibreOffice did not produce the output file.": "O LibreOffice não gerou o arquivo de saída.",
    "The .{ext} has a syntax error.": "O .{ext} tem erro de sintaxe.",
    "Output .{ext} is not supported for data.": "Saída .{ext} não suportada para dados.",
    "This data is not a table (list of objects).": "Esses dados não são uma tabela (lista de objetos).",
    "Could not read the font.": "Não consegui ler a fonte.",
    "This font is CFF (PostScript outlines); turning it into .ttf means converting the curves.":
        "Essa fonte é CFF (contornos PostScript); virar .ttf exige converter as curvas.",
    "This font is TrueType; an .otf with TrueType outlines only changes the name.":
        "Essa fonte é TrueType; .otf com contornos TrueType só muda o nome.",
    "Corrupted or password-protected archive.": "Pacote corrompido ou protegido por senha.",
    "File no longer exists: {path}": "Arquivo não existe mais: {path}",
    "No write permission in {folder}.": "Sem permissão de escrita em {folder}.",
    "The tool finished without error but did not produce the file.":
        "A ferramenta terminou sem erro, mas não gerou o arquivo.",
    "Not enough memory for this conversion.": "Faltou memória para essa conversão.",
    "File error: {error}": "Erro de arquivo: {error}",
    "Unexpected failure: {error}": "Falha inesperada: {error}",

    # ---- errors (how to fix)
    "Install it with:\n  sudo apt install {pkg}": "Instale com:\n  sudo apt install {pkg}",
    "Free up disk space or pick another output folder in ⚙.":
        "Libere espaço no disco ou escolha outra pasta de saída no ⚙.",
    "Pick another output folder in ⚙ (outer ring of the wheel) or check the file permissions.":
        "Escolha outra pasta de saída no ⚙ (anel externo da roda) ou confira as permissões do arquivo.",
    "Open the file in a player to confirm. If the extension is wrong, rename it to the right one.":
        "Abra o arquivo num player para confirmar. Se a extensão estiver errada, renomeie para a certa.",
    "Download/record it again. A truncated file has no index and cannot be converted.":
        "Baixe/grave de novo. Arquivo truncado não tem índice e não converte.",
    "Try another output format or install the full ffmpeg: sudo apt install ffmpeg":
        "Tente outro formato de saída ou instale o ffmpeg completo: sudo apt install ffmpeg",
    "Pick a format that matches what the file contains.": "Escolha um formato compatível com o conteúdo do arquivo.",
    "In ⚙, turn off 'copy without re-encoding' or pick mp4/mkv.":
        "No ⚙, desligue 'copiar sem recodificar' ou escolha mp4/mkv.",
    "Remove the PDF password before converting.": "Remova a senha do PDF antes de converter.",
    "In ⚙, pick a resolution from the list (it is always even).":
        "No ⚙, escolha uma resolução da lista (ela já sai par).",
    "Open it in LibreOffice to check the file is intact; if it is protected, remove the password.":
        "Abra no LibreOffice para ver se o arquivo está íntegro; se for protegido, remova a senha.",
    "See the technical details below. Try ⚙ (outer ring) with simpler settings, or another output format.":
        "Veja os detalhes técnicos abaixo. Tente o ⚙ (anel externo) com ajustes mais simples, "
        "ou outro formato de saída.",
    "Open it in the image viewer to check. HEIC/AVIF need the GdkPixbuf loader "
    "(sudo apt install heif-gdk-pixbuf).":
        "Abra no visualizador de imagens para conferir. HEIC/AVIF exigem o loader do GdkPixbuf "
        "(sudo apt install heif-gdk-pixbuf).",
    "Check that the video has sound. Without audio there is nothing to extract.":
        "Confira se o vídeo tem som. Sem áudio não há o que extrair.",
    "Use seconds (90), mm:ss (1:30) or hh:mm:ss.": "Use segundos (90) ou mm:ss (1:30) ou hh:mm:ss.",
    "Use something like: 1-3,5,8-": "Use algo como: 1-3,5,8-",
    "Adjust the page range in ⚙.": "Ajuste o intervalo de páginas no ⚙.",
    "Open it in a PDF reader to check.": "Abra num leitor de PDF para conferir.",
    "It needs OCR. Install it with: sudo apt install ocrmypdf and run: ocrmypdf input.pdf output.pdf":
        "Precisa de OCR. Instale com: sudo apt install ocrmypdf e rode: ocrmypdf entrada.pdf saida.pdf",
    "This kind of document may not convert to .{ext}. Try PDF, or open it in LibreOffice and use 'Save as'.":
        "Esse tipo de documento talvez não converta para .{ext}. Tente PDF, ou abra no LibreOffice e use "
        "'Salvar como'.",
    "Open it in an editor and fix the line shown in the details.":
        "Abra no editor e corrija a linha indicada nos detalhes.",
    'CSV/spreadsheet only comes out of a list of objects, e.g. [{"name":..}, ..]. Use JSON or YAML as output.':
        'CSV/planilha só sai de uma lista de objetos, ex.: [{"nome":..}, ..]. Use JSON ou YAML como saída.',
    "Corrupted or unsupported font file.": "Arquivo de fonte corrompido ou não suportado.",
    "Use .otf as output (same content), or woff/woff2 for the web.":
        "Use .otf como saída (mesmo conteúdo), ou woff/woff2 para web.",
    "Use .ttf as output, or woff/woff2 for the web.": "Use .ttf como saída, ou woff/woff2 para web.",
    "Try opening it in the archive manager. Password-protected zip is not supported.":
        "Teste abrir no gerenciador de pacotes. Zip com senha não é suportado.",
    "It was moved or deleted. Point to it again.": "Ele foi movido ou apagado. Aponte de novo.",
    "Use ⚙ (outer ring of the wheel) and pick another output folder.":
        "Use o ⚙ (anel externo da roda) e escolha outra pasta de saída.",
    "Try ⚙ with other settings (e.g. a trim range or frame time within the file's duration).":
        "Tente pelo ⚙ com outros ajustes (ex.: trecho de corte ou instante dentro da duração do arquivo).",
    "Close heavy programs or lower the resolution in ⚙.": "Feche programas pesados ou reduza a resolução no ⚙.",
    "Free up space or pick another folder in ⚙.": "Libere espaço ou escolha outra pasta no ⚙.",
    "Check permissions and disk space.": "Confira permissões e espaço em disco.",
    "Try ⚙ with different settings, or another format. If it happens again, the details below show where "
    "it broke.":
        "Tente pelo ⚙ com ajustes diferentes, ou outro formato. Se repetir, os detalhes abaixo mostram onde "
        "quebrou.",
}
