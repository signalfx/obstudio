.PHONY: build test

SUBDIRS := $(sort $(dir $(wildcard */*/Makefile */*/makefile)))

build test:
	@for dir in $(SUBDIRS); do \
		$(MAKE) -C $$dir $@ || exit $$?; \
	done
