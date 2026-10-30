//go:build linux

package credentials

import (
	"context"
	"fmt"

	"github.com/godbus/dbus/v5"
	ss "github.com/zalando/go-keyring/secret_service"
)

const secretServiceName = "org.freedesktop.secrets"
const secretServicePath = dbus.ObjectPath("/org/freedesktop/secrets")
const secretServiceInterface = "org.freedesktop.Secret.Service"
const secretCollectionInterface = "org.freedesktop.Secret.Collection"
const secretItemInterface = "org.freedesktop.Secret.Item"

type platformBackend struct{}

func withSecretService(ctx context.Context, operation func(context.Context, *dbus.Conn, dbus.BusObject, dbus.BusObject) (string, error)) (string, error) {
	conn, err := dbus.ConnectSessionBus(dbus.WithContext(ctx))
	if err != nil {
		return "", ErrUnavailable
	}
	defer conn.Close()
	service := conn.Object(secretServiceName, secretServicePath)
	var collections dbus.Variant
	err = service.CallWithContext(ctx, "org.freedesktop.DBus.Properties.Get", 0, secretServiceInterface, "Collections").Store(&collections)
	if err != nil {
		return "", ErrUnavailable
	}
	paths, ok := collections.Value().([]dbus.ObjectPath)
	if !ok {
		return "", ErrUnavailable
	}
	collectionPath := dbus.ObjectPath("/org/freedesktop/secrets/aliases/default")
	for _, candidate := range paths {
		if candidate == "/org/freedesktop/secrets/collection/login" {
			collectionPath = candidate
			break
		}
	}
	collection := conn.Object(secretServiceName, collectionPath)
	var locked dbus.Variant
	err = collection.CallWithContext(ctx, "org.freedesktop.DBus.Properties.Get", 0, secretCollectionInterface, "Locked").Store(&locked)
	if err != nil || locked.Value() != false {
		return "", ErrUnavailable
	}
	// Never invoke Unlock or Prompt: the desktop must already have unlocked the store.
	return operation(ctx, conn, service, collection)
}

func findSecretItem(ctx context.Context, conn *dbus.Conn, collection dbus.BusObject, key string) (dbus.BusObject, error) {
	var items []dbus.ObjectPath
	err := collection.CallWithContext(ctx, secretCollectionInterface+".SearchItems", 0, map[string]string{"username": key, "service": serviceName}).Store(&items)
	if err != nil {
		return nil, ErrUnavailable
	}
	if len(items) == 0 {
		return nil, ErrNotFound
	}
	return conn.Object(secretServiceName, items[0]), nil
}

func secretSession(ctx context.Context, conn *dbus.Conn, service dbus.BusObject) (dbus.BusObject, error) {
	var output dbus.Variant
	var path dbus.ObjectPath
	if err := service.CallWithContext(ctx, secretServiceInterface+".OpenSession", 0, "plain", dbus.MakeVariant("")).Store(&output, &path); err != nil {
		return nil, ErrUnavailable
	}
	return conn.Object(secretServiceName, path), nil
}

func (platformBackend) Get(key string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), credentialOperationTimeout)
	defer cancel()
	return withSecretService(ctx, func(ctx context.Context, conn *dbus.Conn, service, collection dbus.BusObject) (string, error) {
		item, err := findSecretItem(ctx, conn, collection, key)
		if err != nil {
			return "", err
		}
		session, err := secretSession(ctx, conn, service)
		if err != nil {
			return "", err
		}
		defer session.CallWithContext(ctx, "org.freedesktop.Secret.Session.Close", 0)
		var value ss.Secret
		if err := item.CallWithContext(ctx, secretItemInterface+".GetSecret", 0, session.Path()).Store(&value); err != nil {
			return "", ErrUnavailable
		}
		return string(value.Value), nil
	})
}

func (platformBackend) Set(key, value string) error {
	_, err := withSecretService(context.Background(), func(ctx context.Context, conn *dbus.Conn, service, collection dbus.BusObject) (string, error) {
		session, err := secretSession(ctx, conn, service)
		if err != nil {
			return "", err
		}
		defer session.CallWithContext(ctx, "org.freedesktop.Secret.Session.Close", 0)
		properties := map[string]dbus.Variant{
			secretItemInterface + ".Label":      dbus.MakeVariant(fmt.Sprintf("Password for '%s' on '%s'", key, serviceName)),
			secretItemInterface + ".Attributes": dbus.MakeVariant(map[string]string{"username": key, "service": serviceName}),
		}
		var item, prompt dbus.ObjectPath
		err = collection.CallWithContext(ctx, secretCollectionInterface+".CreateItem", 0, properties, ss.NewSecret(session.Path(), value), true).Store(&item, &prompt)
		if err != nil || prompt != "/" {
			return "", ErrWritePending
		}
		return "", nil
	})
	return err
}

func (platformBackend) Delete(key string) error {
	_, err := withSecretService(context.Background(), func(ctx context.Context, conn *dbus.Conn, service, collection dbus.BusObject) (string, error) {
		item, err := findSecretItem(ctx, conn, collection, key)
		if err != nil {
			return "", err
		}
		var prompt dbus.ObjectPath
		if err := item.CallWithContext(ctx, secretItemInterface+".Delete", 0).Store(&prompt); err != nil || prompt != "/" {
			return "", ErrUnavailable
		}
		return "", nil
	})
	return err
}
