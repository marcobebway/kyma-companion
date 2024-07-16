# Define variables
REGISTRY := marcobebway
IMAGE_NAME := companion
TAG ?= dev

# Default target executed when no arguments are given to make.
default: docker-build

.PHONY: docker-build
docker-build:
	docker build -t $(IMAGE_NAME):$(TAG) .

.PHONY: docker-tag
docker-tag:
	docker tag $(IMAGE_NAME):$(TAG) $(REGISTRY)/$(IMAGE_NAME):$(TAG)

.PHONY: docker-push
docker-push: docker-tag
	docker push $(REGISTRY)/$(IMAGE_NAME):$(TAG)

# Target for building, tagging, and pushing the Docker image.
.PHONY: docker-release
docker-release: docker-build docker-push
