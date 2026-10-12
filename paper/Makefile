# Paper build targets.
#
# html / tex : pandoc >= 3.0 only, no LaTeX distribution required.
# pdf        : rendered from the HTML by headless Chrome. This is the primary
#              PDF route because it needs no TeX toolchain at all and honours
#              paper.css, including the @page rules that set A4 and the margins.
# texpdf     : the LaTeX route; requires pdflatex + bibtex.
#
# The affiliation block in healthenv.md is raw HTML on purpose: pandoc passes
# it through to the HTML/PDF output verbatim (so the RsiingSI logo renders) and
# strips the tags for main.tex, which keeps \author{RsiingSI ...} as plain text.

MD = healthenv.md
BIB = references.bib
TITLE = "HealthEnv: Compiling Longitudinal Health QA into Verifiable Computer-Use Environments"
CHROME ?= /c/Program Files/Google/Chrome/Application/chrome.exe
PDF = healthenv-paper.pdf

.PHONY: all html tex pdf texpdf clean

all: html tex pdf

html: healthenv-paper.html

tex: main.tex

pdf: $(PDF)

healthenv-paper.html: $(MD) $(BIB) paper.css
	pandoc $(MD) -o $@ \
		--standalone \
		--metadata title=$(TITLE) \
		--css paper.css \
		--toc --toc-depth=3 \
		--citeproc --bibliography $(BIB)

main.tex: $(MD) $(BIB)
	pandoc $(MD) -o $@ \
		--standalone \
		--metadata title=$(TITLE) \
		--citeproc --bibliography $(BIB) --natbib

# --print-to-pdf must be an ABSOLUTE path: Chrome resolves a relative one
# against its own working directory, so the file silently never appears next
# to this Makefile. `pwd -W` is the Git Bash idiom for a Windows-style path.
$(PDF): healthenv-paper.html paper.css figures/rsiingsi-logo.png
	"$(CHROME)" --headless=new --disable-gpu --no-sandbox \
		--disable-dev-shm-usage --run-all-compositor-stages-before-draw \
		--virtual-time-budget=20000 --no-pdf-header-footer \
		--print-to-pdf="$$(pwd -W)/$(PDF)" \
		"file://$$(pwd -W)/healthenv-paper.html"

texpdf: main.tex
	pdflatex -interaction=nonstopmode main.tex
	bibtex main || true
	pdflatex -interaction=nonstopmode main.tex
	pdflatex -interaction=nonstopmode main.tex

clean:
	rm -f main.aux main.log main.out main.toc main.bbl main.blg main.pdf $(PDF)
