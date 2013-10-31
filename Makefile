prefix=/usr/local
exec_prefix=$(prefix)
bindir=$(prefix)/bin
libdir=$(prefix)/lib

INSTALL = install
INSTALL_PROGRAM = $(INSTALL)
INSTALL_DATA = $(INSTALL) -m 644

.PHONY: help
help:
	@echo "Targets:"
	@echo
	@echo "  install    [DESTDIR=''] [prefix='/usr/local']"
	@echo "  uninstall  [DESTDIR=''] [prefix='/usr/local']"

.PHONY: all
all: help

.PHONY : aptirepo-env
aptirepo-env:
	echo "#!/bin/sh" > $@
	echo "export APTIREPO_LIBDIR=$(libdir)/aptirepo" >> $@

.PHONY: installdirs
installdirs:
	mkdir -p $(DESTDIR)$(bindir)
	mkdir -p $(DESTDIR)$(libdir)/aptirepo

.PHONY: install
install: aptirepo-env installdirs
	$(INSTALL_PROGRAM) -t $(DESTDIR)$(bindir) aptirepo-env
	$(INSTALL_PROGRAM) -t $(DESTDIR)$(bindir) aptirepo-import
	$(INSTALL_PROGRAM) -t $(DESTDIR)$(bindir) aptirepo-init
	$(INSTALL_PROGRAM) -t $(DESTDIR)$(bindir) aptirepo-update
	$(INSTALL_DATA) -t $(DESTDIR)$(libdir)/aptirepo common.sh
	rm -f aptirepo-env

.PHONY: uninstallfiles
uninstallfiles:
	rm -f $(DESTDIR)$(bindir)/aptirepo-import
	rm -f $(DESTDIR)$(bindir)/aptirepo-init
	rm -f $(DESTDIR)$(bindir)/aptirepo-update
	rm -f $(DESTDIR)$(libdir)/aptirepo common.sh

.PHONY: uninstalldirs
uninstalldirs: uninstallfiles
	rmdir --ignore-fail-on-non-empty -p $(DESTDIR)$(bindir)
	rmdir --ignore-fail-on-non-empty -p $(DESTDIR)$(libdir)/aptirepo

.PHONY: uninstall
uninstall: uninstalldirs

.PHONY: clean
clean:
