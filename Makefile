.PHONY: build clean

build:
	go build -o bp .

clean:
	go fmt ./...
