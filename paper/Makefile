# Paper build targets. Requires pandoc >= 3.0 (no LaTeX required for the HTML target).

MD = healthenv.md
BIB = references.bib
TITLE = "HealthEnv: Compiling Static Health QA Benchmarks into Executable Computer-Use Environments"

.PHONY: all html tex pdf clean

all: html tex

html: healthenv-paper.html

tex: main.tex

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

pdf: main.tex
	pdflatex -interaction=nonstopmode main.tex
	bibtex main || true
	pdflatex -interaction=nonstopmode main.tex
	pdflatex -interaction=nonstopmode main.tex

clean:
	rm -f main.aux main.log main.out main.toc main.bbl main.blg main.pdf
