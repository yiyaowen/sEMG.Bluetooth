#include "common.h"

void vTask1(void* pvParameters)
{
    for ( ;; )
    {
        printf("Task 1 is running");
    }
}

void vTask2(void* pvParameters)
{
    for ( ;; )
    {
        printf("Task 2 is running");
    }
}

int main(void)
{
    InitUart(9600);

    xTaskCreate(vTask1, "Task 1", 1000, NULL, 1, NULL);
    xTaskCreate(vTask2, "Task 2", 1000, NULL, 1, NULL);
    
    vTaskStartScheduler();
    
    for ( ;; ) ;
}
