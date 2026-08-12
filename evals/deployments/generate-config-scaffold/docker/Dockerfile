FROM eclipse-temurin:21-jre
WORKDIR /service
COPY target/entity-model-service.jar /service/entity-model-service.jar
EXPOSE 8080
ENTRYPOINT ["java", "-javaagent:/opt/splunk/otel-javaagent.jar", "-jar", "/service/entity-model-service.jar"]
