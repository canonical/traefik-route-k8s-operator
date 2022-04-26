# traefik-route-k8s-operator

## Developing

Create and activate a virtualenv with the development requirements:

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

## Code overview

This operator acts as a middlecharm between `traefik-k8s` and another charm in 
need of ingress via `ingress-per-unit`.  It uses the `ingress-per-unit` library 
as well as a `traefik-route` lib that implement the two facades of the charm.
It is a workload-less charm so you'll find it pretty simple, the only 
interesting events concern the relation data, and the workload status closely
reflect the health of the relations the charm requires to function.

## Testing

Test with `tox`.