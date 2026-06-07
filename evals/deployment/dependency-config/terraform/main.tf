resource "helm_release" "orders_api" {
  name      = "orders-api"
  namespace = "orders-prod"
  chart     = "../chart"

  values = [
    file("../dependency-values/prod/orders-api-dependencies.yaml")
  ]
}
