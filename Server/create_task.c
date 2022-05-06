#include "common.h"

void vTask1(void* pvParameters)
{
    const char* pcTaskName = "Task 1 is running";
    volatile uint32_t ul; // Use volatile in case ul is optimized away.
    
    for ( ;; )
    {
        printf("%s\n", pcTaskName);
        for (ul = 0; ul < 1000000; ++ul) ; // A crude delay implementation.
    }
}

void vTask2(void* pvParameters)
{
    const char* pcTaskName = "Task 2 is running";
    volatile uint32_t ul;
    
    for ( ;; )
    {
        printf("%s\n", pcTaskName);
        for (ul = 0; ul < 1000000; ++ul) ;
    }
}

int main(void)
{
    xTaskCreate(vTask1, "Task 1", 1000, NULL, 1, NULL);
    xTaskCreate(vTask2, "Task 2", 1000, NULL, 1, NULL);
    
    vTaskStartScheduler();
    
    for ( ;; ) ;
}
