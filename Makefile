PREFIX ?= /usr/local
BINDIR = $(PREFIX)/bin
DATADIR = $(PREFIX)/share/arch-control-center
DESKTOPDIR = $(PREFIX)/share/applications
ICONDIR = $(PREFIX)/share/icons/hicolor/scalable/apps

install:
	@echo "Installing Arch Control Center..."
	install -d $(DESTDIR)$(BINDIR)
	install -d $(DESTDIR)$(DATADIR)
	install -d $(DESTDIR)$(DATADIR)/ui
	install -d $(DESTDIR)$(DATADIR)/assets
	install -d $(DESTDIR)$(DESKTOPDIR)
	install -d $(DESTDIR)$(ICONDIR)

	install -m 755 main.py $(DESTDIR)$(DATADIR)/main.py
	install -m 644 backend.py $(DESTDIR)$(DATADIR)/backend.py
	cp -r ui/* $(DESTDIR)$(DATADIR)/ui/
	cp assets/* $(DESTDIR)$(DATADIR)/assets/

	install -m 644 assets/arch-control-center.svg $(DESTDIR)$(ICONDIR)/arch-control-center.svg
	install -m 644 arch-control-center.desktop $(DESTDIR)$(DESKTOPDIR)/arch-control-center.desktop

	@echo "#!/bin/sh" > $(DESTDIR)$(BINDIR)/arch-control-center
	@echo "exec /usr/bin/python3 $(DATADIR)/main.py \"\$$@\"" >> $(DESTDIR)$(BINDIR)/arch-control-center
	chmod 755 $(DESTDIR)$(BINDIR)/arch-control-center

	@if command -v update-desktop-database > /dev/null 2>&1; then \
		update-desktop-database $(DESTDIR)$(DESKTOPDIR); \
	fi
	@echo "Installation complete. Run 'arch-control-center' to launch."

uninstall:
	@echo "Uninstalling Arch Control Center..."
	rm -f $(DESTDIR)$(BINDIR)/arch-control-center
	rm -rf $(DESTDIR)$(DATADIR)
	rm -f $(DESTDIR)$(DESKTOPDIR)/arch-control-center.desktop
	rm -f $(DESTDIR)$(ICONDIR)/arch-control-center.svg
	@if command -v update-desktop-database > /dev/null 2>&1; then \
		update-desktop-database $(DESTDIR)$(DESKTOPDIR); \
	fi
	@echo "Uninstallation complete."

.PHONY: install uninstall
