SHELL := /bin/bash
VERSION := $(shell dpkg-parsechangelog -S Version)

.PHONY: test deb test-deb clean

test:
	python3 -m unittest discover -s tests -p 'test_*.py' -v
	bash tests/test-shell.sh

deb: test
	dpkg-buildpackage --no-sign -b

test-deb:
	bash tests/test-deb.sh ../yogabook-gnss_$(VERSION)_all.deb

clean:
	@:
