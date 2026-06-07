resource "helm_release" "orders_api" {
  name      = "orders-api"
  namespace = "orders-prod"
  chart     = "../chart"

  values = [
    file("../env-values/prod/orders-api.yaml")
  ]
}
