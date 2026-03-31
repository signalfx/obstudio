BINARY   := obstudio
CMD      := ./cmd/obstudio
BUILD_DIR := .

GO       := go
GOFLAGS  ?=

VERSION  ?= 0.1.0
LDFLAGS  := -ldflags "-X main.version=$(VERSION)"

.PHONY: build run test clean tidy fmt vet

build:
	$(GO) build $(GOFLAGS) $(LDFLAGS) -o $(BUILD_DIR)/$(BINARY) $(CMD)

run: build
	$(BUILD_DIR)/$(BINARY)

test:
	$(GO) test ./...

clean:
	rm -f $(BUILD_DIR)/$(BINARY)

tidy:
	$(GO) mod tidy

fmt:
	$(GO) fmt ./...

vet:
	$(GO) vet ./...
