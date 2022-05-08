#include "common.h"

int main(void)
{
    InitUart(9600);
    
    for ( ;; )
    {
        UartTransmit(UartReceive());
    }
}
