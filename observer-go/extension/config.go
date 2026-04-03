package extension

import "errors"

type Config struct {
	Endpoint string `mapstructure:"endpoint"`
}

func (c *Config) Validate() error {
	if c.Endpoint == "" {
		return errors.New("endpoint is required")
	}
	return nil
}
